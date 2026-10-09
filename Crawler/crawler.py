"""
Crawler/crawler.py
CrawlEngine — the main orchestrator for CrawlMind.

Architecture:
  - Producer-consumer: seeds → Frontier → N worker tasks → Result queue → DB writer
  - Each worker fetches, parses, deduplicates, and enqueues new links
  - Single DB-writer task prevents SQLite WAL locking issues
  - Graceful shutdown on SIGINT/SIGTERM: in-flight tasks marked as processing
    so --resume can pick them up next run
  - Optional PostPageProcessor protocol for LLM (non-blocking)
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import urlparse

from Crawler.crawl_queue import CrawlFrontier
from Crawler.fetcher import AiohttpFetcher, Fetcher
from Crawler.models import CrawlTask, FetchResult, SkipReason, UrlStatus
from Crawler.rate_limiter import RateLimiter
from Crawler.retry_policy import RetryPolicy
from Crawler.robots_manager import RobotsManager
from Crawler.url_normalizer import extract_domain, is_internal_link, normalize_url
from Crawler.url_policy import UrlPolicy
from Exporter.change_detector import compute_change
from Exporter.sqlite_repository import SQLiteRepository
from Parser.html_parser import HtmlParser
from Parser.models import ParsedPage
from Utilities.config import Settings
from Utilities.constants import PRIORITY_DEPTH_PENALTY, PRIORITY_SEED
from Utilities.exceptions import (
    CrawlTimeoutError,
    FetchError,
    InvalidURLError,
    RobotsTxtError,
    SecurityValidationError,
)
from Utilities.logging_config import set_log_context
from Utilities.statistics import StatsCollector
from Utilities.validators import validate_seed_url

logger = logging.getLogger(__name__)


class PostPageProcessor(Protocol):
    """Optional hook called after each page is persisted."""

    async def process(self, page: ParsedPage, page_id: int, run_id: int) -> None:
        """Process a successfully persisted page."""
        ...


@dataclass
class CrawlResult:
    """Summary returned after CrawlEngine.run() completes."""

    run_id: int
    stats: dict[str, Any]
    status: str


class CrawlEngine:
    """
    Main async crawl engine.

    Args:
        settings:        Application settings.
        repository:      Open SQLite repository.
        post_processors: Optional list of PostPageProcessor hooks.
    """

    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        post_processors: Optional[list[PostPageProcessor]] = None,
    ) -> None:
        self._settings = settings
        self._repo = repository
        self._post_processors: list[PostPageProcessor] = post_processors or []
        self._stats = StatsCollector()
        self._executor = ThreadPoolExecutor(max_workers=4)  # for sync parse
        self._shutdown = asyncio.Event()

    async def run(
        self,
        seed_urls: list[str],
        resume_run_id: Optional[int] = None,
    ) -> CrawlResult:
        """
        Start (or resume) a crawl.

        Args:
            seed_urls:      List of seed URLs.
            resume_run_id:  If set, resume from this run ID.

        Returns:
            CrawlResult with run_id, stats, and status.
        """
        # Validate seeds
        validated_seeds: list[str] = []
        for raw_url in seed_urls:
            try:
                url = validate_seed_url(raw_url)
                normalized = normalize_url(url)
                validated_seeds.append(normalized)
            except (InvalidURLError, Exception) as exc:
                logger.error("Invalid seed URL %r: %s", raw_url, exc)

        if not validated_seeds:
            raise ValueError("No valid seed URLs provided")

        seed_domains: set[str] = {extract_domain(u) for u in validated_seeds}

        # Create or resume crawl run
        if resume_run_id:
            run_id = resume_run_id
            logger.info("Resuming crawl run #%d", run_id)
        else:
            run_id = await self._repo.create_crawl_run(
                seeds=validated_seeds,
                config={
                    "max_depth": self._settings.max_depth,
                    "max_pages": self._settings.max_pages,
                    "global_concurrency": self._settings.global_concurrency,
                    "respect_robots_txt": self._settings.respect_robots_txt,
                },
                user_agent=self._settings.user_agent,
            )

        self._stats = StatsCollector(run_id=run_id)
        set_log_context(run_id=str(run_id))

        # Build shared components
        fetcher = AiohttpFetcher(self._settings)
        rate_limiter = RateLimiter(self._settings)
        retry_policy = RetryPolicy(self._settings)
        frontier = CrawlFrontier()
        url_policy = UrlPolicy(
            self._settings,
            seed_domains=seed_domains,
            pages_so_far=lambda: self._stats.snapshot().pages_queued,
        )
        robots_manager = RobotsManager(fetcher._session, self._settings)
        parser = HtmlParser()

        # Result queue (frontier → DB writer)
        result_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        # Register shutdown signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except (NotImplementedError, RuntimeError):
                pass  # Windows doesn't support add_signal_handler fully

        # Populate frontier
        if resume_run_id:
            queued_rows = await self._repo.get_urls_by_status(run_id, UrlStatus.QUEUED)
            processing_rows = await self._repo.get_urls_by_status(run_id, UrlStatus.PROCESSING)
            resume_tasks = [
                CrawlTask(
                    url=row["url"],
                    depth=row["depth"],
                    parent_url=row["parent_url"],
                    priority=row["priority"],
                    domain=row["domain"],
                )
                for row in (queued_rows + processing_rows)
            ]
            await frontier.restore_from_db(resume_tasks)
        else:
            for url in validated_seeds:
                task = CrawlTask(
                    url=url,
                    depth=0,
                    priority=PRIORITY_SEED,
                    domain=extract_domain(url),
                )
                if await frontier.add(task):
                    await self._repo.upsert_url(
                        run_id, url, extract_domain(url), 0, UrlStatus.QUEUED
                    )
                    self._stats.inc_queued()
                    self._stats.inc_discovered()

        # Start workers and DB writer
        n_workers = self._settings.global_concurrency
        workers = [
            asyncio.create_task(
                self._worker(
                    worker_id=i,
                    frontier=frontier,
                    fetcher=fetcher,
                    rate_limiter=rate_limiter,
                    retry_policy=retry_policy,
                    robots_manager=robots_manager,
                    url_policy=url_policy,
                    parser=parser,
                    result_queue=result_queue,
                    run_id=run_id,
                    seed_domains=seed_domains,
                )
            )
            for i in range(n_workers)
        ]
        db_writer_task = asyncio.create_task(
            self._db_writer(result_queue, run_id, seed_domains)
        )

        # Wait for completion or shutdown
        try:
            await frontier.join()
        except asyncio.CancelledError:
            logger.info("Crawl cancelled")
        finally:
            self._shutdown.set()
            # Send sentinels to unblock workers
            await frontier.send_sentinel(n_workers)
            for w in workers:
                w.cancel()
            # Drain result queue
            await result_queue.join()
            result_queue.put_nowait(None)  # sentinel for DB writer
            await db_writer_task
            await fetcher.close()

        # Finalize
        final_status = "completed" if not self._shutdown.is_set() else "interrupted"
        await self._repo.finish_crawl_run(run_id, final_status)

        stats_dict = self._stats.to_dict()
        self._stats.print_table()
        logger.info("Crawl finished: run_id=%d status=%s", run_id, final_status)
        return CrawlResult(run_id=run_id, stats=stats_dict, status=final_status)

    def _handle_shutdown(self) -> None:
        logger.info("Shutdown signal received — stopping gracefully")
        self._shutdown.set()

    # ── Worker ──────────────────────────────────────────────────────────────────

    async def _worker(
        self,
        worker_id: int,
        frontier: CrawlFrontier,
        fetcher: Fetcher,
        rate_limiter: RateLimiter,
        retry_policy: RetryPolicy,
        robots_manager: RobotsManager,
        url_policy: UrlPolicy,
        parser: HtmlParser,
        result_queue: asyncio.Queue,
        run_id: int,
        seed_domains: set[str],
    ) -> None:
        """Worker coroutine: pick task → fetch → parse → enqueue result."""
        while not self._shutdown.is_set():
            try:
                task = await asyncio.wait_for(frontier.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if self._shutdown.is_set():
                    break
                continue

            if task.url == "__SENTINEL__":
                frontier.task_done()
                break

            set_log_context(url=task.url, domain=task.domain)
            self._stats.inc_processing()

            try:
                await self._process_task(
                    task=task,
                    frontier=frontier,
                    fetcher=fetcher,
                    rate_limiter=rate_limiter,
                    retry_policy=retry_policy,
                    robots_manager=robots_manager,
                    url_policy=url_policy,
                    parser=parser,
                    result_queue=result_queue,
                    run_id=run_id,
                    seed_domains=seed_domains,
                )
            except Exception as exc:
                logger.exception("Unhandled exception in worker %d for %s: %s", worker_id, task.url, exc)
                self._stats.inc_failed()
                await frontier.mark_failed(task.url)
                await self._repo.upsert_url(
                    run_id, task.url, task.domain, task.depth, UrlStatus.FAILED
                )
            finally:
                frontier.task_done()

    async def _process_task(
        self,
        task: CrawlTask,
        frontier: CrawlFrontier,
        fetcher: Fetcher,
        rate_limiter: RateLimiter,
        retry_policy: RetryPolicy,
        robots_manager: RobotsManager,
        url_policy: UrlPolicy,
        parser: HtmlParser,
        result_queue: asyncio.Queue,
        run_id: int,
        seed_domains: set[str],
    ) -> None:
        """Core task processing logic."""
        url = task.url
        domain = task.domain

        # Policy check (depth, domain, length, traps)
        skip_reason = url_policy.evaluate(task)
        if skip_reason:
            self._stats.inc_skipped()
            await frontier.mark_visited(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.SKIPPED)
            logger.debug("Skipped %s: %s", url, skip_reason.value)
            return

        # Robots.txt check
        try:
            can_fetch = await robots_manager.can_fetch(url)
        except RobotsTxtError as exc:
            logger.warning("Robots block for %s: %s", url, exc)
            self._stats.inc_blocked_robots()
            await frontier.mark_blocked(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.BLOCKED_BY_ROBOTS)
            await self._repo.insert_audit_event(run_id, "blocked_by_robots", url, str(exc))
            return

        if not can_fetch:
            self._stats.inc_blocked_robots()
            await frontier.mark_blocked(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.BLOCKED_BY_ROBOTS)
            await self._repo.insert_audit_event(run_id, "blocked_by_robots", url)
            return

        # Rate limiting
        robots_delay = await robots_manager.get_crawl_delay(domain)
        if robots_delay:
            rate_limiter.set_domain_delay(domain, robots_delay)

        # Fetch with retry loop
        fetch_result: Optional[FetchResult] = None
        last_exc: Optional[BaseException] = None
        last_status: Optional[int] = None

        # Get cached ETag/Last-Modified for conditional GET
        existing_page = await self._repo.get_page_by_url(run_id, url)
        etag = existing_page.get("etag") if existing_page else None
        last_modified = existing_page.get("last_modified") if existing_page else None

        for attempt in range(self._settings.max_retries + 1):
            try:
                async with rate_limiter.acquire(domain):
                    fetch_result = await fetcher.fetch(task, etag=etag, last_modified=last_modified)
                last_status = fetch_result.status_code
                rate_limiter.record_result(domain, last_status, robots_delay)
                self._stats.add_response_time(fetch_result.response_time_ms)
                self._stats.inc_status(last_status)
                break

            except SecurityValidationError as exc:
                self._stats.inc_blocked_security()
                await frontier.mark_blocked(url)
                await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.BLOCKED_BY_SECURITY)
                await self._repo.insert_audit_event(run_id, "ssrf_blocked", url, str(exc))
                logger.warning("Security block for %s: %s", url, exc)
                return

            except (FetchError, CrawlTimeoutError) as exc:
                last_exc = exc
                decision = retry_policy.evaluate(
                    url, attempt, exception=exc
                )
                self._stats.inc_retries()
                if not decision.should_retry:
                    break
                await retry_policy.wait(decision.delay_seconds)

        # Determine final outcome
        if fetch_result is None or (last_status and last_status >= 400):
            # Permanent failure
            error_type = type(last_exc).__name__ if last_exc else f"http_{last_status}"
            error_msg = str(last_exc) if last_exc else f"HTTP {last_status}"
            self._stats.inc_failed()
            await frontier.mark_failed(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.FAILED, retry_count=task.retry_count + 1)
            await self._repo.insert_error(run_id, url, error_type, error_msg, last_status, task.retry_count)
            self._stats.inc_error(error_type)
            return

        # 304 Not Modified
        if fetch_result.is_not_modified:
            self._stats.inc_successful()
            await frontier.mark_visited(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.SUCCESS)
            self._stats.add_bytes(0, saved=existing_page.get("bytes_downloaded", 0) if existing_page else 0)
            logger.info("Not modified (304): %s", url)
            return

        # Non-HTML — skip parsing but record
        if not fetch_result.is_html:
            self._stats.inc_skipped()
            await frontier.mark_visited(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.SKIPPED)
            return

        # Parse in thread pool (CPU-bound)
        loop = asyncio.get_event_loop()
        parsed_page: ParsedPage = await loop.run_in_executor(
            self._executor,
            lambda: parser.parse(fetch_result, self._settings.store_raw_html),
        )

        # Duplicate detection by content hash
        if await self._repo.hash_exists(parsed_page.content_hash):
            self._stats.inc_duplicate()
            await frontier.mark_visited(url)
            await self._repo.upsert_url(run_id, url, domain, task.depth, UrlStatus.DUPLICATE)
            logger.debug("Duplicate content: %s", url)
            return

        # Change detection (if recrawling same URL)
        if existing_page and existing_page.get("content_hash") != parsed_page.content_hash:
            old_text = existing_page.get("cleaned_text") or ""
            score, added, removed = compute_change(old_text, parsed_page.cleaned_text)
            await self._repo.insert_page_change(
                url=url,
                old_page_id=existing_page.get("id"),
                new_page_id=0,  # will be updated after insert
                old_hash=existing_page.get("content_hash"),
                new_hash=parsed_page.content_hash,
                change_score=score,
                added_text=added,
                removed_text=removed,
            )

        # Enqueue to result queue for DB writer
        await result_queue.put((run_id, task, fetch_result, parsed_page))

        # Enqueue new links
        new_link_count = await self._enqueue_links(
            parsed_page=parsed_page,
            frontier=frontier,
            url_policy=url_policy,
            run_id=run_id,
            current_depth=task.depth,
        )
        logger.info(
            "Fetched %s depth=%d status=%d links=%d words=%d",
            url, task.depth, fetch_result.status_code, new_link_count, parsed_page.word_count,
        )

    async def _enqueue_links(
        self,
        parsed_page: ParsedPage,
        frontier: CrawlFrontier,
        url_policy: UrlPolicy,
        run_id: int,
        current_depth: int,
    ) -> int:
        """Normalize and enqueue internal links discovered on a page."""
        added = 0
        next_depth = current_depth + 1

        for link in parsed_page.internal_links:
            try:
                norm_url = normalize_url(link.url)
            except (InvalidURLError, Exception):
                continue

            if frontier.has_url(norm_url):
                continue

            domain = extract_domain(norm_url)
            priority = PRIORITY_SEED + (next_depth * PRIORITY_DEPTH_PENALTY)
            new_task = CrawlTask(
                url=norm_url,
                depth=next_depth,
                parent_url=parsed_page.final_url,
                priority=priority,
                domain=domain,
            )
            if await frontier.add(new_task):
                await self._repo.upsert_url(
                    run_id, norm_url, domain, next_depth,
                    UrlStatus.QUEUED, parent_url=parsed_page.final_url
                )
                self._stats.inc_queued()
                self._stats.inc_discovered()
                added += 1

        return added

    # ── DB Writer ───────────────────────────────────────────────────────────────

    async def _db_writer(
        self,
        result_queue: asyncio.Queue,
        run_id: int,
        seed_domains: set[str],
    ) -> None:
        """
        Single-task DB writer: reads from result_queue and persists pages.
        Exits when it receives None sentinel.
        """
        while True:
            item = await result_queue.get()
            if item is None:
                result_queue.task_done()
                break

            run_id_item, task, fetch_result, parsed_page = item
            url = task.url

            try:
                url_id = await self._repo.get_url_id(run_id_item, url)
                if url_id is None:
                    url_id = await self._repo.upsert_url(
                        run_id_item, url, task.domain, task.depth, UrlStatus.SUCCESS
                    )
                else:
                    await self._repo.upsert_url(
                        run_id_item, url, task.domain, task.depth, UrlStatus.SUCCESS
                    )

                page_id = await self._repo.insert_page(
                    run_id=run_id_item,
                    url_id=url_id,
                    page=parsed_page,
                    bytes_downloaded=len(fetch_result.raw_bytes),
                    bytes_saved=fetch_result.bytes_saved,
                )
                self._stats.inc_successful()
                self._stats.add_bytes(
                    len(fetch_result.raw_bytes),
                    saved=fetch_result.bytes_saved,
                )

                # Keyword frequency update
                words = parsed_page.cleaned_text.lower().split()
                from collections import Counter
                term_counts = dict(Counter(words))
                await self._repo.upsert_keyword_frequency(
                    run_id_item, term_counts, {t: 1 for t in term_counts}
                )

                # Post-processors (LLM, etc.)
                for proc in self._post_processors:
                    try:
                        await proc.process(parsed_page, page_id, run_id_item)
                    except Exception as exc:
                        logger.warning("PostPageProcessor error: %s", exc)

            except Exception as exc:
                logger.exception("DB writer error for %s: %s", url, exc)
                self._stats.inc_error("db_write_error")
            finally:
                result_queue.task_done()
