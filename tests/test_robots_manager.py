"""tests/test_robots_manager.py"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
from Crawler.robots_manager import RobotsManager, _CachedRobots, _parse_robots


class TestRobotsManager:
    @pytest.fixture
    def robots_manager(self, settings):
        session = AsyncMock()
        return RobotsManager(session, settings)

    @pytest.mark.asyncio
    async def test_can_fetch_allowed(self, robots_manager, robots_txt_content, settings):
        rp, delay, sitemaps = _parse_robots(robots_txt_content, "*")
        cached = _CachedRobots(robots=rp, fetched_at=0, crawl_delay=delay, sitemap_urls=sitemaps)
        robots_manager._get_cached = AsyncMock(return_value=cached)
        
        allowed = await robots_manager.can_fetch("https://example.com/public/page", user_agent="*")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_can_fetch_disallowed(self, robots_manager, robots_txt_content, settings):
        rp, delay, sitemaps = _parse_robots(robots_txt_content, "*")
        cached = _CachedRobots(robots=rp, fetched_at=0, crawl_delay=delay, sitemap_urls=sitemaps)
        robots_manager._get_cached = AsyncMock(return_value=cached)
        
        allowed = await robots_manager.can_fetch("https://example.com/private/page", user_agent="*")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_specific_user_agent_disallow(self, robots_manager, robots_txt_content, settings):
        rp, delay, sitemaps = _parse_robots(robots_txt_content, settings.user_agent)
        cached = _CachedRobots(robots=rp, fetched_at=0, crawl_delay=delay, sitemap_urls=sitemaps)
        robots_manager._get_cached = AsyncMock(return_value=cached)
        
        allowed = await robots_manager.can_fetch("https://example.com/blocked-for-crawlmind/")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_get_crawl_delay(self, robots_manager, robots_txt_content, settings):
        rp, delay, sitemaps = _parse_robots(robots_txt_content, "*")
        cached = _CachedRobots(robots=rp, fetched_at=0, crawl_delay=delay, sitemap_urls=sitemaps)
        robots_manager._get_cached = AsyncMock(return_value=cached)
        
        delay_val = await robots_manager.get_crawl_delay("example.com")
        assert delay_val == 1.0

    @pytest.mark.asyncio
    async def test_robots_fetch_fails_allows_all(self, robots_manager):
        # If robots.txt fails to load, default is to allow (is_missing=True)
        cached = _CachedRobots(robots=None, fetched_at=0, crawl_delay=None, sitemap_urls=[], is_missing=True)
        robots_manager._get_cached = AsyncMock(return_value=cached)
        
        allowed = await robots_manager.can_fetch("https://example.com/secret")
        assert allowed is True
