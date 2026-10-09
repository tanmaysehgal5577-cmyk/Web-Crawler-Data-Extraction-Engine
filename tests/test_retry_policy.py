"""tests/test_retry_policy.py"""

from __future__ import annotations

import pytest
import aiohttp
import asyncio
from Crawler.retry_policy import RetryPolicy
from Utilities.exceptions import FetchError, CrawlTimeoutError


class TestRetryPolicy:
    def test_evaluate_success(self, settings):
        policy = RetryPolicy(settings)
        decision = policy.evaluate("http://example.com", 0, exception=None)
        assert not decision.should_retry
        assert decision.delay_seconds == 0.0

    def test_evaluate_timeout(self, settings):
        policy = RetryPolicy(settings)
        decision = policy.evaluate("http://example.com", 0, exception=CrawlTimeoutError("Timeout"))
        assert decision.should_retry
        assert decision.delay_seconds > 0.0

    def test_evaluate_max_retries_exceeded(self, settings):
        policy = RetryPolicy(settings)
        # Assuming settings.max_retries is 3
        decision = policy.evaluate("http://example.com", settings.max_retries, exception=CrawlTimeoutError("Timeout"))
        assert not decision.should_retry

    def test_evaluate_fatal_error(self, settings):
        policy = RetryPolicy(settings)
        # ClientConnectorError usually means domain doesn't exist etc.
        exc = FetchError("DNS resolution failed")
        decision = policy.evaluate("http://example.com", 0, exception=exc)
        assert not decision.should_retry

    def test_backoff_increases_with_attempts(self, settings):
        policy = RetryPolicy(settings)
        d1 = policy.evaluate("http://example.com", 0, exception=CrawlTimeoutError("")).delay_seconds
        d2 = policy.evaluate("http://example.com", 1, exception=CrawlTimeoutError("")).delay_seconds
        d3 = policy.evaluate("http://example.com", 2, exception=CrawlTimeoutError("")).delay_seconds
        assert d2 >= d1
        assert d3 >= d2
