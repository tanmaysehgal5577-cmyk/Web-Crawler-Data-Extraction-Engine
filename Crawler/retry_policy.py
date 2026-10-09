"""
Crawler/retry_policy.py
Retry decision logic and exponential backoff for CrawlMind.

Retries only transient failures:
  - aiohttp.ClientConnectionError
  - asyncio.TimeoutError
  - HTTP 408, 425, 429, 500, 502, 503, 504

Never retries most 4xx permanent errors.
Supports Retry-After header parsing for 429/503.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from Utilities.config import Settings
from Utilities.constants import PERMANENT_ERROR_STATUS_CODES, RETRYABLE_STATUS_CODES
from Utilities.exceptions import RetryExhaustedError, CrawlTimeoutError

logger = logging.getLogger(__name__)


@dataclass
class RetryDecision:
    """Outcome of a retry evaluation."""

    should_retry: bool
    delay_seconds: float
    reason: str


class RetryPolicy:
    """
    Evaluates whether to retry a failed request and computes the wait delay.

    Args:
        settings: Application settings (max_retries, base_delay, max_delay).
    """

    def __init__(self, settings: Settings) -> None:
        self._max_retries = settings.max_retries
        self._base_delay = settings.base_retry_delay_seconds
        self._max_delay = settings.max_retry_delay_seconds

    def evaluate(
        self,
        url: str,
        attempt: int,
        *,
        status_code: Optional[int] = None,
        exception: Optional[BaseException] = None,
        retry_after_header: Optional[str] = None,
    ) -> RetryDecision:
        """
        Decide whether to retry.

        Args:
            url:               URL being fetched (for logging).
            attempt:           Current attempt number (0-indexed).
            status_code:       HTTP status code (None if exception).
            exception:         Exception raised (None if HTTP error).
            retry_after_header: Value of Retry-After header from response.

        Returns:
            RetryDecision with should_retry flag and delay.
        """
        if attempt >= self._max_retries:
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                reason=f"max retries ({self._max_retries}) exhausted",
            )

        # Check if the error is retryable
        retryable, reason = self._is_retryable(status_code=status_code, exception=exception)
        if not retryable:
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                reason=reason,
            )

        delay = self._compute_delay(attempt, retry_after_header)
        logger.info(
            "Retry scheduled",
            extra={
                "url": url,
                "retry": attempt + 1,
                "delay": delay,
                "reason": reason,
            },
        )
        return RetryDecision(should_retry=True, delay_seconds=delay, reason=reason)

    def _is_retryable(
        self,
        status_code: Optional[int],
        exception: Optional[BaseException],
    ) -> tuple[bool, str]:
        """Return (is_retryable, reason_string)."""
        if exception is not None:
            if isinstance(exception, (asyncio.TimeoutError, CrawlTimeoutError)):
                return True, "timeout"
            if isinstance(exception, aiohttp.ClientConnectionError):
                return True, "connection_error"
            if isinstance(exception, aiohttp.ServerDisconnectedError):
                return True, "server_disconnected"
            if isinstance(exception, aiohttp.ClientPayloadError):
                return True, "payload_error"
            return False, f"non-retryable exception: {type(exception).__name__}"

        if status_code is None:
            return False, "no status code and no exception"

        if status_code in RETRYABLE_STATUS_CODES:
            return True, f"http_{status_code}"

        if status_code in PERMANENT_ERROR_STATUS_CODES:
            return False, f"permanent http_{status_code}"

        if 200 <= status_code < 300:
            return False, "success"

        # Any other 4xx — treat as non-retryable
        if 400 <= status_code < 500:
            return False, f"client error http_{status_code}"

        return False, f"unhandled status {status_code}"

    def _compute_delay(
        self,
        attempt: int,
        retry_after_header: Optional[str],
    ) -> float:
        """
        Compute retry delay.

        Priority:
          1. Retry-After header (if valid and <= max_delay)
          2. Exponential backoff with jitter:
             delay = min(max_delay, base * 2^attempt) + uniform(0, 1)
        """
        # Try Retry-After header first
        if retry_after_header:
            try:
                ra = float(retry_after_header)
                if 0 < ra <= self._max_delay:
                    return ra
            except ValueError:
                pass

        # Exponential backoff
        backoff = self._base_delay * (2 ** attempt)
        capped = min(self._max_delay, backoff)
        jitter = random.uniform(0, 1.0)
        return round(capped + jitter, 3)

    async def wait(self, delay: float) -> None:
        """Async sleep for *delay* seconds."""
        await asyncio.sleep(delay)
