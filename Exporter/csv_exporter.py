"""
Exporter/csv_exporter.py
Exports crawl data to CSV files.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from Utilities.exceptions import ExportError

logger = logging.getLogger(__name__)

_PAGE_FIELDS = [
    "id", "run_id", "original_url", "final_url", "canonical_url",
    "status_code", "content_type", "content_length", "response_time_ms",
    "depth", "language", "title", "meta_description", "author",
    "published_at", "modified_at", "word_count", "reading_time_min",
    "quality_score", "is_low_quality", "content_hash", "crawled_at",
]

_ERROR_FIELDS = [
    "id", "run_id", "url", "error_type", "error_message",
    "http_status", "retry_count", "occurred_at",
]


class CsvExporter:
    """Exports pages and errors to CSV files."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def export_pages(
        self, pages: list[dict[str, Any]], run_id: int
    ) -> Path:
        """Export pages to CSV with selected columns."""
        out_path = self._output_dir / f"pages_run_{run_id}.csv"
        try:
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=_PAGE_FIELDS,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(pages)
            logger.info("Exported %d pages (CSV) -> %s", len(pages), out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write CSV: {exc}") from exc

    async def export_errors(
        self, errors: list[dict[str, Any]], run_id: int
    ) -> Path:
        """Export crawl errors to CSV."""
        out_path = self._output_dir / f"errors_run_{run_id}.csv"
        try:
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=_ERROR_FIELDS,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(errors)
            logger.info("Exported %d errors (CSV) -> %s", len(errors), out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write errors CSV: {exc}") from exc

    async def export_keywords(
        self, keywords: list[dict[str, Any]], run_id: int
    ) -> Path:
        """Export keyword frequency to CSV."""
        out_path = self._output_dir / f"keywords_run_{run_id}.csv"
        try:
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["term", "frequency", "doc_frequency"],
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(keywords)
            logger.info("Exported %d keywords (CSV) -> %s", len(keywords), out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write keywords CSV: {exc}") from exc
