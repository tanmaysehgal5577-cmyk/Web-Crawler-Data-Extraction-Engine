"""
Utilities/validators.py
Input validators used across CrawlMind.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from Utilities.exceptions import InvalidURLError

# Hostname validation regex (simplified — IDNA handled separately in normalizer)
_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"\.)*"
    r"[a-zA-Z]{2,63}$"
)


def validate_seed_url(url: str) -> str:
    """
    Basic validation that *url* is a well-formed http/https URL.

    Returns the URL unchanged if valid.
    Raises InvalidURLError otherwise.
    """
    if not url or not isinstance(url, str):
        raise InvalidURLError("URL must be a non-empty string")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise InvalidURLError(
            f"Seed URL must start with http:// or https://, got: {url!r}"
        )

    parsed = urlparse(url)
    if not parsed.netloc:
        raise InvalidURLError(f"URL has no netloc (host): {url!r}")

    hostname = parsed.hostname or ""
    if not hostname:
        raise InvalidURLError(f"URL has no hostname: {url!r}")

    if len(url) > 8192:
        raise InvalidURLError(f"URL too long ({len(url)} chars): {url[:80]!r}...")

    return url


def is_valid_run_id(run_id: str) -> bool:
    """Return True if run_id looks like a valid integer string."""
    return bool(run_id) and run_id.isdigit()
