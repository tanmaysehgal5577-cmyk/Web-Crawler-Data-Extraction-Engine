"""tests/conftest.py — Shared pytest fixtures."""

from __future__ import annotations

import os
import asyncio
import pytest
import aiosqlite
from pathlib import Path

# Force test environment
os.environ.update({
    "CRAWLER_MAX_DEPTH": "2",
    "CRAWLER_MAX_PAGES": "100",
    "CRAWLER_GLOBAL_CONCURRENCY": "5",
    "CRAWLER_PER_DOMAIN_CONCURRENCY": "2",
    "CRAWLER_REQUEST_TIMEOUT_SECONDS": "30",
    "CRAWLER_CONNECT_TIMEOUT_SECONDS": "10",
    "CRAWLER_READ_TIMEOUT_SECONDS": "20",
    "CRAWLER_DATABASE_PATH": ":memory:",
    "CRAWLER_LOG_LEVEL": "ERROR",
    "CRAWLER_LOG_FORMAT": "console",
    "CRAWLER_BLOCK_PRIVATE_NETWORKS": "true",
    "CRAWLER_ENABLE_LLM": "false",
    "LLM_PROVIDER": "disabled",
})


@pytest.fixture
def settings():
    from Utilities.config import load_settings
    return load_settings()


@pytest.fixture
async def db(tmp_path):
    """Temporary in-memory SQLite database with migrations applied."""
    from Exporter.sqlite_repository import SQLiteRepository
    db_path = tmp_path / "test.db"
    repo = SQLiteRepository(db_path)
    await repo.open()
    yield repo
    await repo.close()


@pytest.fixture
def sample_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Test Page</title>
  <meta name="description" content="A test page for CrawlMind">
  <meta property="og:title" content="OG Test Title">
  <link rel="canonical" href="https://example.com/test">
</head>
<body>
  <nav>Navigation links</nav>
  <h1>Main Heading</h1>
  <h2>Subheading</h2>
  <p>This is a test paragraph with enough words to pass quality checks.</p>
  <p>Another paragraph with some content to test the parser functionality.</p>
  <a href="/internal-page">Internal Link</a>
  <a href="https://external.com/page">External Link</a>
  <img src="/image.jpg" alt="Test image" width="100" height="100">
  <footer>Footer content</footer>
</body>
</html>"""


@pytest.fixture
def malformed_html() -> str:
    return "<html><body><p>Unclosed paragraph<div>Nested wrong<p>More text</body>"


@pytest.fixture
def robots_txt_content() -> str:
    return """User-agent: *
Disallow: /private/
Disallow: /admin/
Allow: /public/
Crawl-delay: 1

User-agent: CrawlMind
Disallow: /blocked-for-crawlmind/

Sitemap: https://example.com/sitemap.xml
"""
