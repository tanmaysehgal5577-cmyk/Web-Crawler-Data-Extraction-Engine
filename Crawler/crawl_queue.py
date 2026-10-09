"""
Crawler/crawl_queue.py
Async priority frontier (crawl queue) with in-memory deduplication.

Architecture:
  - asyncio.PriorityQueue as the backing store
  - Separate sets for visited, queued, processing, failed URLs
  - Resume support: pre-populate from DB on startup
  - Sentinel-based clean shutdown
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Set

from Crawler.models import CrawlTask, UrlStatus

logger = logging.getLogger(__name__)

_SENTINEL: CrawlTask = CrawlTask(url="__SENTINEL__", depth=-1)


class CrawlFrontier:
    """
    Thread/async-safe URL frontier.

    Maintains five sets for accurate state tracking:
      - queued     : in queue, not yet picked up
      - processing : picked up by a worker, not yet complete
      - visited    : successfully fetched (or permanently skipped)
      - failed     : exhausted retries
      - blocked    : security / robots block

    URL membership is normalised before insertion.

    Args:
        max_size: Maximum queue size (0 = unlimited).
    """

    def __init__(self, max_size: int = 0) -> None:
        self._queue: asyncio.PriorityQueue[CrawlTask] = asyncio.PriorityQueue(
            maxsize=max_size
        )
        self._queued: Set[str] = set()
        self._processing: Set[str] = set()
        self._visited: Set[str] = set()
        self._failed: Set[str] = set()
        self._blocked: Set[str] = set()
        self._lock = asyncio.Lock()
        self._total_added = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    async def add(self, task: CrawlTask) -> bool:
        """
        Add *task* to the frontier if its URL has not been seen before.

        Args:
            task: CrawlTask to enqueue.

        Returns:
            True if the task was added, False if already seen.
        """
        async with self._lock:
            url = task.url
            if self._is_seen(url):
                return False
            self._queued.add(url)
            self._total_added += 1
        await self._queue.put(task)
        return True

    async def get(self) -> CrawlTask:
        """
        Get next task from the frontier.

        Moves URL from queued → processing.
        Blocks until a task is available.

        Returns:
            Next CrawlTask (may be sentinel for shutdown).
        """
        task = await self._queue.get()
        if task is not _SENTINEL:
            async with self._lock:
                self._queued.discard(task.url)
                self._processing.add(task.url)
        return task

    def task_done(self) -> None:
        """Signal that the queue item has been processed (for queue.join())."""
        self._queue.task_done()

    async def mark_visited(self, url: str) -> None:
        """Mark URL as successfully crawled (processing → visited)."""
        async with self._lock:
            self._processing.discard(url)
            self._visited.add(url)

    async def mark_failed(self, url: str) -> None:
        """Mark URL as permanently failed (processing → failed)."""
        async with self._lock:
            self._processing.discard(url)
            self._failed.add(url)

    async def mark_blocked(self, url: str) -> None:
        """Mark URL as blocked (processing → blocked)."""
        async with self._lock:
            self._processing.discard(url)
            self._blocked.add(url)

    async def requeue(self, task: CrawlTask) -> None:
        """Move URL from processing back to queued (for retry / resume)."""
        async with self._lock:
            self._processing.discard(task.url)
            self._queued.add(task.url)
        await self._queue.put(task)

    def has_url(self, url: str) -> bool:
        """Return True if URL is already known (queued / processing / visited)."""
        return self._is_seen(url)

    def _is_seen(self, url: str) -> bool:
        return (
            url in self._queued
            or url in self._processing
            or url in self._visited
            or url in self._failed
            or url in self._blocked
        )

    async def send_sentinel(self, n: int = 1) -> None:
        """Send *n* sentinel tasks to unblock waiting workers."""
        for _ in range(n):
            await self._queue.put(_SENTINEL)

    async def join(self) -> None:
        """Wait until all queued tasks have been processed."""
        await self._queue.join()

    # ── State / stats ──────────────────────────────────────────────────────────

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def total_added(self) -> int:
        return self._total_added

    @property
    def n_queued(self) -> int:
        return len(self._queued)

    @property
    def n_processing(self) -> int:
        return len(self._processing)

    @property
    def n_visited(self) -> int:
        return len(self._visited)

    @property
    def n_failed(self) -> int:
        return len(self._failed)

    @property
    def n_blocked(self) -> int:
        return len(self._blocked)

    # ── Resume support ─────────────────────────────────────────────────────────

    async def restore_from_db(self, tasks: list[CrawlTask]) -> int:
        """
        Pre-populate frontier from DB (for --resume).

        Skips URLs already in visited/failed/blocked sets.

        Returns:
            Number of tasks actually added.
        """
        added = 0
        for task in tasks:
            if await self.add(task):
                added += 1
        logger.info("Restored %d tasks from database for resume", added)
        return added
