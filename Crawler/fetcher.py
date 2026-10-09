"""
Crawler/fetcher.py
HTTP fetcher with manual redirect handling, conditional GET, and SSRF protection.

Key design decisions:
  - allow_redirects=False: each redirect hop is revalidated (robots, security, policy)
  - Streamed reads with configurable size cap
  - ETag / If-Modified-Since support for bandwidth-efficient recrawling
  - SafeResolver integrated into TCPConnector for DNS-rebinding defence
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from Crawler.models import CrawlTask, FetchResult
from Utilities.config import Settings
from Utilities.exceptions import CrawlTimeoutError, FetchError, SecurityValidationError
from Utilities.security import SafeResolver, validate_url_security

logger = logging.getLogger(__name__)


class Fetcher(ABC):
    """Abstract base class for page fetchers."""

    @abstractmethod
    async def fetch(
        self,
        task: CrawlTask,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> FetchResult:
        """
        Fetch the URL in *task*.

        Args:
            task:          CrawlTask with URL and metadata.
            etag:          Previous ETag for conditional GET.
            last_modified: Previous Last-Modified for conditional GET.

        Returns:
            FetchResult.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close underlying session / resources."""


class AiohttpFetcher(Fetcher):
    """
    Production HTTP fetcher using aiohttp.

    Features:
      - Connection pooling via shared ClientSession
      - SafeResolver (post-DNS IP validation)
      - Manual redirect following (revalidate each hop)
      - Configurable timeouts (connect / read / total)
      - Streaming read with size cap
      - Conditional GET (ETag, Last-Modified)
      - Structured error logging
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._timeout = aiohttp.ClientTimeout(
            total=settings.request_timeout_seconds,
            connect=settings.connect_timeout_seconds,
            sock_read=settings.read_timeout_seconds,
        )
        resolver = SafeResolver(block_private_networks=settings.block_private_networks)
        connector = aiohttp.TCPConnector(
            limit=settings.global_concurrency,
            limit_per_host=settings.per_domain_concurrency,
            resolver=resolver,  # type: ignore[arg-type]
            ssl=None,           # use default SSL context
        )
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=self._timeout,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )

    async def fetch(
        self,
        task: CrawlTask,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> FetchResult:
        """
        Fetch *task.url* with optional conditional GET headers.

        Raises:
            FetchError:             On HTTP error or connection failure.
            CrawlTimeoutError:      On timeout.
            SecurityValidationError: If a redirect target is blocked.
        """
        url = task.url
        start = time.monotonic()
        redirect_chain: list[str] = []
        max_redirects = self._settings.max_redirects

        # Pre-flight security check
        try:
            validate_url_security(url, self._settings.block_private_networks)
        except SecurityValidationError:
            raise

        # Build request headers
        request_headers: dict[str, str] = {}
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified

        current_url = url
        for hop in range(max_redirects + 1):
            try:
                async with self._session.get(
                    current_url,
                    headers=request_headers,
                    allow_redirects=False,
                    max_line_size=8190,
                ) as resp:
                    # Handle redirect
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location", "")
                        if not location:
                            break
                        # Resolve relative redirect
                        from urllib.parse import urljoin
                        next_url = urljoin(current_url, location)

                        # Revalidate redirect target
                        validate_url_security(
                            next_url, self._settings.block_private_networks
                        )

                        redirect_chain.append(current_url)
                        current_url = next_url
                        request_headers = {}  # Clear conditional headers after redirect
                        logger.debug("Redirect %d: %s -> %s", hop + 1, url, current_url)
                        continue

                    # Handle 304 Not Modified
                    if resp.status == 304:
                        elapsed_ms = (time.monotonic() - start) * 1000
                        headers_dict = dict(resp.headers)
                        parsed = urlparse(current_url)
                        return FetchResult(
                            url=url,
                            final_url=current_url,
                            status_code=304,
                            content_type=resp.headers.get("Content-Type", ""),
                            content_length=0,
                            raw_bytes=b"",
                            response_time_ms=elapsed_ms,
                            depth=task.depth,
                            headers=headers_dict,
                            etag=resp.headers.get("ETag"),
                            last_modified=resp.headers.get("Last-Modified"),
                            is_not_modified=True,
                            bytes_saved=0,
                            redirect_chain=redirect_chain,
                        )

                    # Read body with size cap
                    max_bytes = self._settings.max_response_bytes
                    raw_bytes = await self._read_capped(resp, max_bytes)

                    elapsed_ms = (time.monotonic() - start) * 1000
                    content_type = resp.headers.get("Content-Type", "")
                    content_length = int(resp.headers.get("Content-Length", len(raw_bytes)))

                    return FetchResult(
                        url=url,
                        final_url=current_url,
                        status_code=resp.status,
                        content_type=content_type,
                        content_length=content_length,
                        raw_bytes=raw_bytes,
                        response_time_ms=elapsed_ms,
                        depth=task.depth,
                        headers=dict(resp.headers),
                        etag=resp.headers.get("ETag"),
                        last_modified=resp.headers.get("Last-Modified"),
                        is_not_modified=False,
                        bytes_saved=0,
                        redirect_chain=redirect_chain,
                    )

            except asyncio.TimeoutError as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                raise CrawlTimeoutError(
                    f"Timeout after {elapsed_ms:.0f}ms fetching {current_url}",
                    url=url,
                ) from exc

            except aiohttp.ClientError as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                raise FetchError(
                    f"Client error after {elapsed_ms:.0f}ms: {exc}",
                    url=url,
                ) from exc

        # Redirect loop exhausted
        raise FetchError(
            f"Too many redirects (>{max_redirects}) for {url}",
            url=url,
        )

    async def _read_capped(
        self,
        resp: aiohttp.ClientResponse,
        max_bytes: int,
    ) -> bytes:
        """Read response body, capping at max_bytes."""
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.content.iter_chunked(65536):
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                logger.warning(
                    "Response truncated at %d bytes for %s", max_bytes, resp.url
                )
                break
        return b"".join(chunks)

    async def close(self) -> None:
        """Close the underlying aiohttp ClientSession."""
        await self._session.close()
