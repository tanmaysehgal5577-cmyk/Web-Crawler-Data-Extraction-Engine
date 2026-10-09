"""
Utilities/exceptions.py
Custom exception hierarchy for CrawlMind.

NOTE: The spec mentions a 'TimeoutError' exception, but that name shadows
      the Python builtin. We use CrawlTimeoutError throughout the codebase.
"""

from __future__ import annotations


class CrawlMindError(Exception):
    """Base class for all CrawlMind exceptions."""


# ── Configuration ──────────────────────────────────────────────────────────────

class ConfigurationError(CrawlMindError):
    """Raised when a configuration value is invalid or missing."""


# ── URL / Policy ───────────────────────────────────────────────────────────────

class InvalidURLError(CrawlMindError):
    """Raised when a URL cannot be parsed or is structurally invalid."""


# ── Robots ─────────────────────────────────────────────────────────────────────

class RobotsTxtError(CrawlMindError):
    """Raised when robots.txt cannot be fetched and policy = deny_on_error."""


# ── Network / Fetching ─────────────────────────────────────────────────────────

class FetchError(CrawlMindError):
    """Generic fetch failure (connection refused, DNS failure, etc.)."""

    def __init__(
        self,
        message: str,
        url: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class CrawlTimeoutError(CrawlMindError):
    """Raised when a fetch or LLM call exceeds its configured timeout.

    Named CrawlTimeoutError (not TimeoutError) to avoid shadowing the builtin.
    """

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message)
        self.url = url


class RetryExhaustedError(CrawlMindError):
    """Raised when all retry attempts for a URL have been exhausted."""

    def __init__(self, message: str, url: str = "", attempts: int = 0) -> None:
        super().__init__(message)
        self.url = url
        self.attempts = attempts


# ── Parsing ────────────────────────────────────────────────────────────────────

class ParserError(CrawlMindError):
    """Raised when HTML cannot be parsed (malformed beyond recovery)."""


# ── Storage ────────────────────────────────────────────────────────────────────

class StorageError(CrawlMindError):
    """Raised on database read/write failures."""


# ── Export ─────────────────────────────────────────────────────────────────────

class ExportError(CrawlMindError):
    """Raised when an exporter fails to write output."""


# ── Intelligence / LLM ────────────────────────────────────────────────────────

class LLMServiceError(CrawlMindError):
    """Raised when the LLM call fails after retries."""

    def __init__(self, message: str, provider: str = "", model: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


# ── Security ───────────────────────────────────────────────────────────────────

class SecurityValidationError(CrawlMindError):
    """Raised when a URL fails SSRF / security validation."""

    def __init__(self, message: str, url: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.url = url
        self.reason = reason
