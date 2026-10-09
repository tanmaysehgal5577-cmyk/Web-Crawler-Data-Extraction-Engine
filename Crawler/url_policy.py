"""
Crawler/url_policy.py
URL admission policy for CrawlMind.

Evaluates a CrawlTask against configurable rules and returns a SkipReason
if the URL should not be fetched, or None if it should proceed.

Rules applied (in order):
  1. Unsupported scheme (double-check after normalization)
  2. Domain scope (allowed domains / internal-only)
  3. Max depth
  4. Max URL length
  5. Max query-param count
  6. Non-HTML file extension
  7. Repeated path segment trap
  8. Infinite pagination trap (page=N, offset=N, start=N patterns)
  9. Calendar URL trap (/2023/01/15/-like paths)
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import parse_qs, urlparse

from Crawler.models import CrawlTask, SkipReason
from Utilities.constants import (
    ALLOWED_SCHEMES,
    MAX_REPEATED_SEGMENT_OCCURRENCES,
    NON_HTML_EXTENSIONS,
)
from Utilities.config import Settings

logger = logging.getLogger(__name__)

# Pagination query params that may signal a trap
_PAGINATION_PARAMS: frozenset[str] = frozenset({
    "page", "p", "pg", "paged", "pagenumber",
    "offset", "start", "from", "skip",
    "pageindex", "page_num", "pagenum",
})

# Calendar URL pattern: e.g., /2023/01/ or /2023/01/15/
_CALENDAR_RE = re.compile(
    r"/(?:19|20)\d{2}/(?:0[1-9]|1[0-2])(?:/(?:[0-2]\d|3[01]))?/?$"
)


class UrlPolicy:
    """
    Evaluates whether a URL (wrapped in CrawlTask) should be crawled.

    Args:
        settings:        Application settings.
        seed_domains:    Set of domains extracted from seed URLs.
        pages_so_far:    Callable returning the current count of queued/visited pages.
    """

    def __init__(
        self,
        settings: Settings,
        seed_domains: set[str],
        pages_so_far: "Callable[[], int]" = lambda: 0,  # type: ignore[name-defined]
    ) -> None:
        self._settings = settings
        self._seed_domains = seed_domains
        self._pages_so_far = pages_so_far

    def evaluate(self, task: CrawlTask) -> SkipReason | None:
        """
        Return a SkipReason if the URL should be skipped, else None.

        Args:
            task: CrawlTask to evaluate.

        Returns:
            SkipReason or None.
        """
        url = task.url
        parsed = urlparse(url)

        # 1. Scheme
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            return SkipReason.UNSUPPORTED_SCHEME

        # 2. Domain scope
        domain = (parsed.hostname or "").lower()
        if not self._is_domain_allowed(domain):
            logger.debug("Domain not allowed: %s", domain)
            return SkipReason.DOMAIN_NOT_ALLOWED

        # 3. Depth
        if task.depth > self._settings.max_depth:
            return SkipReason.DEPTH_EXCEEDED

        # 4. Max pages
        if self._pages_so_far() >= self._settings.max_pages:
            return SkipReason.MAX_PAGES_REACHED

        # 5. URL length
        if len(url) > self._settings.max_url_length:
            return SkipReason.URL_TOO_LONG

        # 6. Max query params
        query_params = parse_qs(parsed.query)
        if len(query_params) > self._settings.max_query_params:
            return SkipReason.TOO_MANY_QUERY_PARAMS

        # 7. Non-HTML extension
        path_lower = parsed.path.lower()
        for ext in NON_HTML_EXTENSIONS:
            if path_lower.endswith(ext):
                return SkipReason.NON_HTML_EXTENSION

        # 8. Repeated segment trap
        if self._is_repeated_segment_trap(parsed.path):
            logger.warning("Repeated segment trap detected: %s", url)
            return SkipReason.REPEATED_SEGMENT_TRAP

        # 9. Pagination trap
        if self._is_pagination_trap(query_params):
            return SkipReason.PAGINATION_TRAP

        # 10. Calendar trap
        if _CALENDAR_RE.search(parsed.path):
            return SkipReason.CALENDAR_TRAP

        return None

    # ── Private helpers ────────────────────────────────────────────────────────

    def _is_domain_allowed(self, domain: str) -> bool:
        """Check domain against seed domains and configured allowed list."""
        if not domain:
            return False

        # Explicit allowlist takes priority
        explicit = self._settings.allowed_domains
        if explicit:
            return domain in explicit or any(
                domain == d or domain.endswith("." + d) for d in explicit
            )

        # Allowlist mode: only seed domains + their subdomains
        if self._settings.allowlist_mode:
            return any(
                domain == seed or domain.endswith("." + seed)
                for seed in self._seed_domains
            )

        # Default: follow internal links (seed domain + www variant)
        return any(
            domain == seed
            or domain.endswith("." + seed)
            or seed.endswith("." + domain)
            or domain.lstrip("www.") == seed.lstrip("www.")
            for seed in self._seed_domains
        )

    def _is_repeated_segment_trap(self, path: str) -> bool:
        """
        Detect paths with a segment repeated ≥ MAX_REPEATED_SEGMENT_OCCURRENCES times.
        Example trap: /a/b/a/b/a/b/
        """
        segments = [s for s in path.split("/") if s]
        if not segments:
            return False
        counts = Counter(segments)
        return any(
            count >= MAX_REPEATED_SEGMENT_OCCURRENCES
            for count in counts.values()
            if count > 1
        )

    def _is_pagination_trap(self, query_params: dict[str, list[str]]) -> bool:
        """
        Detect query params that suggest infinite pagination.
        Only flags when a large numeric offset is present (> 10_000).
        """
        for param in _PAGINATION_PARAMS:
            if param in query_params:
                values = query_params[param]
                for val in values:
                    try:
                        n = int(val)
                        if n > 10_000:
                            return True
                    except ValueError:
                        pass
        return False
