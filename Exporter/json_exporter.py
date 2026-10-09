"""
Exporter/json_exporter.py
Exports crawl data to JSON files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from Utilities.exceptions import ExportError

logger = logging.getLogger(__name__)


class JsonExporter:
    """Exports pages, stats, and errors to JSON."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def export_pages(
        self,
        pages: list[dict[str, Any]],
        run_id: int,
        filename: str | None = None,
    ) -> Path:
        """
        Export pages list to JSON.

        Args:
            pages:    List of page dicts.
            run_id:   Crawl run ID (for default filename).
            filename: Override output filename.

        Returns:
            Path to written file.
        """
        fname = filename or f"pages_run_{run_id}.json"
        out_path = self._output_dir / fname
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {"run_id": run_id, "total": len(pages), "pages": pages},
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            logger.info("Exported %d pages -> %s", len(pages), out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write JSON: {exc}") from exc

    async def export_stats(self, stats: dict[str, Any], run_id: int) -> Path:
        """Export crawl statistics to JSON."""
        out_path = self._output_dir / f"stats_run_{run_id}.json"
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
            logger.info("Exported stats -> %s", out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write stats JSON: {exc}") from exc

    async def export_keywords(
        self, keywords: list[dict[str, Any]], run_id: int
    ) -> Path:
        """Export keyword frequency to JSON."""
        out_path = self._output_dir / f"keywords_run_{run_id}.json"
        try:
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(
                    {"run_id": run_id, "keywords": keywords},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.info("Exported %d keywords -> %s", len(keywords), out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write keywords JSON: {exc}") from exc
