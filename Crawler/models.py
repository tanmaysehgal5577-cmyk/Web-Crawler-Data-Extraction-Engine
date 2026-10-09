"""
Crawler/models.py
Data models for the crawler layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class UrlStatus(str, Enum):
    """Lifecycle states of a URL in a crawl run."""

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED_BY_ROBOTS = "blocked_by_robots"
    BLOCKED_BY_SECURITY = "blocked_by_security"
    DUPLICATE = "duplicate"


class SkipReason(str, Enum):
    """Reason a URL was skipped by UrlPolicy."""

    DEPTH_EXCEEDED = "depth_exceeded"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    URL_TOO_LONG = "url_too_long"
    TOO_MANY_QUERY_PARAMS = "too_many_query_params"
    NON_HTML_EXTENSION = "non_html_extension"
    REPEATED_SEGMENT_TRAP = "repeated_segment_trap"
    PAGINATION_TRAP = "pagination_trap"
    CALENDAR_TRAP = "calendar_trap"
    MAX_PAGES_REACHED = "max_pages_reached"
    UNSUPPORTED_SCHEME = "unsupported_scheme"


@dataclass
class CrawlTask:
    """Represents one URL to be fetched."""

    url: str
    depth: int
    parent_url: Optional[str] = None
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0
    priority: int = 0
    domain: str = ""

    def __lt__(self, other: "CrawlTask") -> bool:
        """For priority queue ordering (lower priority value = higher priority)."""
        return self.priority < other.priority


@dataclass
class FetchResult:
    """Result of fetching a single URL."""

    url: str                        # original URL
    final_url: str                  # URL after redirects
    status_code: int
    content_type: str
    content_length: int
    raw_bytes: bytes
    response_time_ms: float
    depth: int
    headers: dict[str, str]
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    is_not_modified: bool = False   # True on HTTP 304
    bytes_saved: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300 or self.is_not_modified

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower().split(";")[0].strip()
        return ct in {"text/html", "application/xhtml+xml"}

    @property
    def decoded_text(self) -> str:
        """Decode raw bytes to UTF-8 text (lossy)."""
        return self.raw_bytes.decode("utf-8", errors="replace")
