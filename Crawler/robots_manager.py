"""
Crawler/robots_manager.py
Robots.txt manager using the Protego library.

Features:
  - Async download (via aiohttp ClientSession passed in)
  - In-memory cache per domain (with TTL)
  - Honours User-Agent, Disallow, Allow, Crawl-delay
  - Extracts Sitemap URLs
  - Configurable failure policy:
      allow_all                 → allow on any error
      deny_all                  → deny on any error
      allow_on_404_deny_on_error → allow on 404, deny on all other errors

NOTE: protego library is used instead of stdlib urllib.robotparser because
      protego correctly handles wildcard rules (* and $) as per Google's spec.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import protego  # type: ignore[import-untyped]

from Utilities.config import Settings
from Utilities.constants import ROBOTS_CACHE_TTL
from Utilities.exceptions import RobotsTxtError

logger = logging.getLogger(__name__)


@dataclass
class _CachedRobots:
    """Cached robots.txt for one domain."""

    robots: Optional[protego.Protego]   # None means "failed / not found"
    fetched_at: float
    crawl_delay: Optional[float]
    sitemap_urls: list[str]
    error: bool = False                 # True if fetch failed (not 404)
    is_missing: bool = False            # True if 404/410


def _parse_robots(content: str, user_agent: str) -> tuple[Optional[protego.Protego], Optional[float], list[str]]:
    """
    Parse robots.txt content.

    Returns:
        (Protego instance | None, crawl_delay | None, sitemap_urls)
    """
    try:
        rp = protego.Protego.parse(content)
    except Exception as exc:
        logger.warning("Failed to parse robots.txt: %s", exc)
        return None, None, []

    # Crawl-delay (per user-agent, then wildcard)
    delay: Optional[float] = None
    try:
        delay_val = rp.crawl_delay(user_agent)
        if delay_val is not None:
            delay = float(delay_val)
    except Exception:
        pass

    # Sitemap URLs
    sitemaps: list[str] = []
    try:
        sitemaps = list(rp.sitemaps)
    except Exception:
        pass

    return rp, delay, sitemaps


class RobotsManager:
    """
    Async robots.txt manager with in-memory caching.

    Args:
        session:  Shared aiohttp ClientSession.
        settings: Application settings.
    """

    def __init__(self, session: aiohttp.ClientSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._cache: dict[str, _CachedRobots] = {}

    async def _fetch_robots(self, domain: str, scheme: str) -> _CachedRobots:
        """Download and parse robots.txt for *domain*."""
        robots_url = f"{scheme}://{domain}/robots.txt"
        logger.debug("Fetching robots.txt: %s", robots_url)

        try:
            async with self._session.get(
                robots_url,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True,
                headers={"User-Agent": self._settings.user_agent},
            ) as resp:
                if resp.status in (404, 410):
                    logger.debug("robots.txt not found (%d): %s", resp.status, robots_url)
                    return _CachedRobots(
                        robots=None,
                        fetched_at=time.monotonic(),
                        crawl_delay=None,
                        sitemap_urls=[],
                        is_missing=True,
                    )

                if resp.status != 200:
                    logger.warning(
                        "robots.txt returned HTTP %d: %s", resp.status, robots_url
                    )
                    return _CachedRobots(
                        robots=None,
                        fetched_at=time.monotonic(),
                        crawl_delay=None,
                        sitemap_urls=[],
                        error=True,
                    )

                content = await resp.text(encoding="utf-8", errors="replace")
                rp, delay, sitemaps = _parse_robots(content, self._settings.user_agent)
                return _CachedRobots(
                    robots=rp,
                    fetched_at=time.monotonic(),
                    crawl_delay=delay,
                    sitemap_urls=sitemaps,
                )

        except Exception as exc:
            logger.warning("Error fetching robots.txt for %s: %s", domain, exc)
            return _CachedRobots(
                robots=None,
                fetched_at=time.monotonic(),
                crawl_delay=None,
                sitemap_urls=[],
                error=True,
            )

    async def _get_cached(self, domain: str, scheme: str) -> _CachedRobots:
        """Return cached entry (refresh if TTL expired)."""
        cached = self._cache.get(domain)
        if cached is None or (time.monotonic() - cached.fetched_at) > ROBOTS_CACHE_TTL:
            self._cache[domain] = await self._fetch_robots(domain, scheme)
        return self._cache[domain]

    async def can_fetch(self, url: str, user_agent: Optional[str] = None) -> bool:
        """
        Return True if the URL may be fetched according to robots.txt.

        Args:
            url:        Full URL to check.
            user_agent: Override user-agent (defaults to settings).

        Raises:
            RobotsTxtError: If policy is deny_on_error and robots.txt fetch failed.
        """
        if not self._settings.respect_robots_txt:
            return True

        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        scheme = parsed.scheme or "https"
        ua = user_agent or self._settings.user_agent

        cached = await self._get_cached(domain, scheme)

        # Handle errors
        if cached.error:
            policy = self._settings.robots_failure_policy
            if policy == "allow_all":
                return True
            if policy == "deny_all":
                raise RobotsTxtError(
                    f"robots.txt fetch failed for {domain} and policy=deny_all"
                )
            # allow_on_404_deny_on_error → deny on real errors
            raise RobotsTxtError(
                f"robots.txt fetch failed for {domain} (policy=allow_on_404_deny_on_error)"
            )

        # Missing (404) → allow
        if cached.is_missing:
            return True

        # Parse check
        if cached.robots is None:
            return True  # no valid parse → be permissive

        try:
            return bool(cached.robots.can_fetch(url, ua))
        except Exception as exc:
            logger.warning("protego.can_fetch error for %s: %s", url, exc)
            return True

    async def get_crawl_delay(self, domain: str, scheme: str = "https") -> Optional[float]:
        """Return robots.txt Crawl-delay for *domain* (or None)."""
        if not self._settings.respect_robots_txt:
            return None
        cached = await self._get_cached(domain, scheme)
        return cached.crawl_delay

    async def get_sitemap_urls(self, domain: str, scheme: str = "https") -> list[str]:
        """Return Sitemap URLs from robots.txt for *domain*."""
        cached = await self._get_cached(domain, scheme)
        return cached.sitemap_urls
