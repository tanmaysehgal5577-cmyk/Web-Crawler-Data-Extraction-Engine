"""
Crawler/rate_limiter.py
Per-domain and global rate limiter for polite crawling.

Each domain gets a DomainState with:
  - An asyncio.Semaphore (per-domain concurrency cap)
  - next_allowed_at: monotonic timestamp after which next request may start
  - penalty_multiplier: increases on 429/503, decreases on success

Global concurrency is enforced by a single shared asyncio.Semaphore.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from Utilities.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class DomainState:
    """Per-domain concurrency and delay state."""

    semaphore: asyncio.Semaphore
    next_allowed_at: float = field(default_factory=time.monotonic)
    penalty_multiplier: float = 1.0        # grows on 429/503
    base_delay: float = 1.0               # seconds

    @property
    def current_delay(self) -> float:
        return self.base_delay * self.penalty_multiplier

    def apply_penalty(self, status_code: int) -> None:
        """Increase delay after rate-limit or server-overload responses."""
        if status_code in (429, 503):
            self.penalty_multiplier = min(32.0, self.penalty_multiplier * 2.0)
            logger.info(
                "Rate-limit penalty applied",
                extra={"status_code": status_code, "multiplier": self.penalty_multiplier},
            )

    def record_success(self) -> None:
        """Gradually reduce penalty after success."""
        if self.penalty_multiplier > 1.0:
            self.penalty_multiplier = max(1.0, self.penalty_multiplier * 0.75)


class RateLimiter:
    """
    Per-domain and global rate limiter.

    Usage::

        async with rate_limiter.acquire(domain):
            result = await fetch(url)
        rate_limiter.record_result(domain, status_code)

    Args:
        settings: Application settings (global/per-domain concurrency, default delay).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._global_sem = asyncio.Semaphore(settings.global_concurrency)
        self._domains: dict[str, DomainState] = {}
        self._lock = asyncio.Lock()
        self._default_delay = settings.default_delay_seconds

    async def _get_domain_state(self, domain: str) -> DomainState:
        async with self._lock:
            if domain not in self._domains:
                self._domains[domain] = DomainState(
                    semaphore=asyncio.Semaphore(self._settings.per_domain_concurrency),
                    base_delay=self._default_delay,
                )
            return self._domains[domain]

    def set_domain_delay(self, domain: str, delay: float) -> None:
        """Override base delay for a domain (e.g., from robots.txt Crawl-delay)."""
        state = self._domains.get(domain)
        if state:
            state.base_delay = max(delay, self._default_delay)
        # If domain not yet registered, delay will be set when first accessed

    @asynccontextmanager
    async def acquire(self, domain: str):
        """
        Async context manager that acquires global + domain semaphores
        and waits until the domain's next_allowed_at timestamp.

        Usage::
            async with rate_limiter.acquire(domain):
                ...
        """
        state = await self._get_domain_state(domain)
        await self._global_sem.acquire()
        try:
            await state.semaphore.acquire()
            try:
                now = time.monotonic()
                wait = state.next_allowed_at - now
                if wait > 0:
                    logger.debug(
                        "Rate limiter waiting %.2fs for domain %s", wait, domain
                    )
                    await asyncio.sleep(wait)
                yield
            finally:
                state.semaphore.release()
        finally:
            self._global_sem.release()

    def record_result(
        self,
        domain: str,
        status_code: int,
        robots_delay: Optional[float] = None,
    ) -> None:
        """
        Record the result of a fetch for this domain.

        Updates next_allowed_at and penalty multiplier.

        Args:
            domain:       Domain that was crawled.
            status_code:  HTTP status code of the response.
            robots_delay: Crawl-delay from robots.txt (overrides default).
        """
        state = self._domains.get(domain)
        if not state:
            return

        if status_code in (429, 503):
            state.apply_penalty(status_code)
        else:
            state.record_success()

        # Compute the delay to apply after this request
        delay = robots_delay if (robots_delay and robots_delay > state.current_delay) else state.current_delay
        state.next_allowed_at = time.monotonic() + delay


        state.next_allowed_at = time.monotonic() + delay
