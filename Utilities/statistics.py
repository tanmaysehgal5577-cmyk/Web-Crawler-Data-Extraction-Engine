"""
Utilities/statistics.py
Real-time crawl statistics collector and reporter.
Thread/async-safe via simple integer counters (GIL-protected) + lock for dict updates.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table


@dataclass
class CrawlStats:
    """Snapshot of crawl statistics at a point in time."""

    run_id: int = 0
    started_at: float = field(default_factory=time.monotonic)

    # Page counts
    pages_discovered: int = 0
    pages_queued: int = 0
    pages_processing: int = 0
    pages_successful: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    pages_duplicate: int = 0
    pages_blocked_robots: int = 0
    pages_blocked_security: int = 0

    # Bandwidth
    bytes_downloaded: int = 0
    bytes_saved_caching: int = 0

    # Timing
    total_response_time_ms: float = 0.0
    response_count: int = 0

    # Retries / Errors
    total_retries: int = 0
    errors_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    status_distribution: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    # LLM
    llm_calls: int = 0
    llm_failures: int = 0
    llm_total_latency_ms: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def pages_per_minute(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return (self.pages_successful / elapsed) * 60

    @property
    def avg_response_time_ms(self) -> float:
        if self.response_count == 0:
            return 0.0
        return self.total_response_time_ms / self.response_count

    @property
    def mb_downloaded(self) -> float:
        return self.bytes_downloaded / (1024 * 1024)

    @property
    def mb_saved(self) -> float:
        return self.bytes_saved_caching / (1024 * 1024)


class StatsCollector:
    """
    Thread/async-safe statistics collector.
    Wraps CrawlStats with atomic increment helpers.
    """

    def __init__(self, run_id: int = 0) -> None:
        self._stats = CrawlStats(run_id=run_id)
        self._lock = asyncio.Lock()

    # ── Increment helpers ──────────────────────────────────────────────────────

    def inc_discovered(self, n: int = 1) -> None:
        self._stats.pages_discovered += n

    def inc_queued(self, n: int = 1) -> None:
        self._stats.pages_queued += n

    def inc_processing(self, n: int = 1) -> None:
        self._stats.pages_processing += n

    def dec_processing(self, n: int = 1) -> None:
        self._stats.pages_processing = max(0, self._stats.pages_processing - n)

    def inc_successful(self) -> None:
        self._stats.pages_successful += 1
        self.dec_processing()

    def inc_failed(self) -> None:
        self._stats.pages_failed += 1
        self.dec_processing()

    def inc_skipped(self) -> None:
        self._stats.pages_skipped += 1

    def inc_duplicate(self) -> None:
        self._stats.pages_duplicate += 1

    def inc_blocked_robots(self) -> None:
        self._stats.pages_blocked_robots += 1

    def inc_blocked_security(self) -> None:
        self._stats.pages_blocked_security += 1

    def add_bytes(self, downloaded: int, saved: int = 0) -> None:
        self._stats.bytes_downloaded += downloaded
        self._stats.bytes_saved_caching += saved

    def add_response_time(self, ms: float) -> None:
        self._stats.total_response_time_ms += ms
        self._stats.response_count += 1

    def inc_retries(self) -> None:
        self._stats.total_retries += 1

    def inc_error(self, error_type: str) -> None:
        self._stats.errors_by_type[error_type] += 1

    def inc_status(self, code: int) -> None:
        self._stats.status_distribution[code] += 1

    def inc_llm_call(self, latency_ms: float, failed: bool = False) -> None:
        self._stats.llm_calls += 1
        self._stats.llm_total_latency_ms += latency_ms
        if failed:
            self._stats.llm_failures += 1

    def snapshot(self) -> CrawlStats:
        """Return a shallow copy of current stats."""
        import copy
        return copy.copy(self._stats)

    def to_dict(self) -> dict[str, Any]:
        """Return stats as a JSON-serialisable dict."""
        s = self._stats
        return {
            "run_id": s.run_id,
            "elapsed_seconds": round(s.elapsed_seconds, 2),
            "pages": {
                "discovered": s.pages_discovered,
                "queued": s.pages_queued,
                "processing": s.pages_processing,
                "successful": s.pages_successful,
                "failed": s.pages_failed,
                "skipped": s.pages_skipped,
                "duplicate": s.pages_duplicate,
                "blocked_robots": s.pages_blocked_robots,
                "blocked_security": s.pages_blocked_security,
            },
            "bandwidth": {
                "bytes_downloaded": s.bytes_downloaded,
                "mb_downloaded": round(s.mb_downloaded, 3),
                "bytes_saved_caching": s.bytes_saved_caching,
                "mb_saved": round(s.mb_saved, 3),
            },
            "performance": {
                "pages_per_minute": round(s.pages_per_minute, 2),
                "avg_response_time_ms": round(s.avg_response_time_ms, 2),
                "total_retries": s.total_retries,
            },
            "http_status_distribution": dict(s.status_distribution),
            "errors_by_type": dict(s.errors_by_type),
            "llm": {
                "calls": s.llm_calls,
                "failures": s.llm_failures,
                "avg_latency_ms": (
                    round(s.llm_total_latency_ms / s.llm_calls, 2)
                    if s.llm_calls
                    else 0.0
                ),
            },
        }

    def print_table(self) -> None:
        """Print a Rich-formatted statistics table to the console."""
        console = Console()
        s = self._stats

        table = Table(
            title=f"[bold cyan]CrawlMind Statistics — Run #{s.run_id}[/bold cyan]",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Metric", style="cyan", width=30)
        table.add_column("Value", justify="right", style="green")

        rows: list[tuple[str, str]] = [
            ("Elapsed", f"{s.elapsed_seconds:.1f}s"),
            ("Pages Discovered", str(s.pages_discovered)),
            ("Pages Successful", str(s.pages_successful)),
            ("Pages Failed", str(s.pages_failed)),
            ("Pages Skipped", str(s.pages_skipped)),
            ("Duplicates Detected", str(s.pages_duplicate)),
            ("Blocked (robots.txt)", str(s.pages_blocked_robots)),
            ("Blocked (security)", str(s.pages_blocked_security)),
            ("Total Retries", str(s.total_retries)),
            ("Pages / Minute", f"{s.pages_per_minute:.1f}"),
            ("Avg Response Time", f"{s.avg_response_time_ms:.0f}ms"),
            ("Data Downloaded", f"{s.mb_downloaded:.2f} MB"),
            ("Data Saved (caching)", f"{s.mb_saved:.2f} MB"),
            ("LLM Calls", str(s.llm_calls)),
            ("LLM Failures", str(s.llm_failures)),
        ]
        for metric, value in rows:
            table.add_row(metric, value)

        console.print(table)

        # HTTP status distribution
        if s.status_distribution:
            status_table = Table(title="HTTP Status Distribution", show_header=True)
            status_table.add_column("Status", style="yellow")
            status_table.add_column("Count", justify="right")
            for code, count in sorted(s.status_distribution.items()):
                status_table.add_row(str(code), str(count))
            console.print(status_table)
