"""
Crawler/url_normalizer.py
Idempotent URL normalisation for CrawlMind.

Operations (in order):
  1. Strip leading/trailing whitespace
  2. Parse URL
  3. Reject unsupported schemes
  4. Lowercase scheme and hostname
  5. Encode/decode IDNA hostname
  6. Remove default ports (80 for http, 443 for https)
  7. Remove userinfo
  8. Resolve dot-segments in path (/../, /./)
  9. Collapse multiple slashes in path
 10. Remove tracking query parameters
 11. Sort remaining query parameters (stable for repeated keys)
 12. Remove URL fragment
 13. Normalize trailing slash (remove unless path is root)
 14. Percent-encode path components that need encoding
"""

from __future__ import annotations

import logging
import re
from urllib.parse import (
    ParseResult,
    parse_qsl,
    quote,
    urlencode,
    urlparse,
    urlunparse,
)

from Utilities.constants import ALLOWED_SCHEMES, TRACKING_PARAMS
from Utilities.exceptions import InvalidURLError

logger = logging.getLogger(__name__)

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

# Characters safe to leave unencoded in path
_PATH_SAFE = "/:@!$&'()*+,;=-._~%"

# Regex: runs of // that are NOT at the start of authority
_MULTI_SLASH_RE = re.compile(r"(?<!:)/{2,}")


def _resolve_dot_segments(path: str) -> str:
    """Implement RFC 3986 §5.2.4 dot-segment removal."""
    if "." not in path:
        return path

    parts: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if parts:
                parts.pop()
        elif segment != ".":
            parts.append(segment)

    # Preserve leading slash
    result = "/".join(parts)
    if path.startswith("/") and not result.startswith("/"):
        result = "/" + result
    return result


def _encode_path(path: str) -> str:
    """Percent-encode path while leaving already-encoded sequences intact."""
    return quote(path, safe=_PATH_SAFE)


def normalize_url(url: str, base_url: str = "") -> str:
    """
    Normalize *url*, optionally resolving it against *base_url*.

    Args:
        url:      Absolute or relative URL to normalize.
        base_url: Base URL for resolving relative URLs.

    Returns:
        Normalized absolute URL string.

    Raises:
        InvalidURLError: If the URL cannot be normalized.
    """
    if not url:
        raise InvalidURLError("URL must be non-empty")

    url = url.strip()

    # Remove fragment early (fragments are never sent to server)
    url = url.split("#")[0]
    if not url:
        raise InvalidURLError("URL was fragment-only")

    # Resolve relative URLs
    if base_url and not url.startswith(("http://", "https://")):
        from urllib.parse import urljoin
        url = urljoin(base_url, url)

    # Parse
    try:
        parsed: ParseResult = urlparse(url)
    except Exception as exc:
        raise InvalidURLError(f"Cannot parse URL: {url!r}") from exc

    scheme = parsed.scheme.lower()
    if not scheme:
        raise InvalidURLError(f"URL has no scheme: {url!r}")
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidURLError(
            f"Unsupported scheme {scheme!r} in URL: {url!r}"
        )

    # Hostname
    hostname = parsed.hostname
    if not hostname:
        raise InvalidURLError(f"URL has no hostname: {url!r}")
    try:
        hostname = hostname.lower().encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        # Non-IDNA hostname — keep lowercase
        hostname = hostname.lower()

    # Port: drop if it's the default for the scheme
    port = parsed.port
    if port == _DEFAULT_PORTS.get(scheme):
        port = None

    # Reconstruct netloc (no userinfo ever)
    netloc = hostname
    if port is not None:
        netloc = f"{hostname}:{port}"

    # Path: dot-segments, multi-slash, trailing slash
    path = parsed.path or "/"
    path = _resolve_dot_segments(path)
    path = _MULTI_SLASH_RE.sub("/", path)
    path = _encode_path(path)

    # Remove trailing slash (except for root path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Query: remove tracking params, sort remaining
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = [
        (k, v) for (k, v) in query_pairs if k.lower() not in TRACKING_PARAMS
    ]
    sorted_pairs = sorted(filtered_pairs, key=lambda kv: kv[0])
    query = urlencode(sorted_pairs)

    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    return normalized


def extract_domain(url: str) -> str:
    """Extract the hostname (domain) from a URL."""
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def is_internal_link(url: str, base_domain: str) -> bool:
    """
    Return True if *url* belongs to *base_domain* or its www-subdomain.

    Handles www stripping: base_domain='example.com' matches 'www.example.com'.
    """
    domain = extract_domain(url)
    if not domain:
        return False
    base = base_domain.lower().lstrip("www.")
    target = domain.lower().lstrip("www.")
    return target == base or target.endswith("." + base)
