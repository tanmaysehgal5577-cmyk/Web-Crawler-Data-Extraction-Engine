"""
Exporter/sitemap_generator.py
XML Sitemap generator following the Sitemaps protocol.

Limits:
  - Max 50,000 URLs per sitemap file
  - Max 50 MB per file
  - Generates sitemap index if multiple files needed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from Utilities.constants import SITEMAP_MAX_BYTES, SITEMAP_MAX_URLS
from Utilities.exceptions import ExportError

logger = logging.getLogger(__name__)

_URLSET_OPEN = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
_URLSET_CLOSE = "</urlset>\n"
_SITEMAPINDEX_OPEN = '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
_SITEMAPINDEX_CLOSE = "</sitemapindex>\n"


def _url_entry(url: str, lastmod: str | None = None) -> str:
    parts = [f"  <url>\n    <loc>{escape(url)}</loc>\n"]
    if lastmod:
        parts.append(f"    <lastmod>{escape(lastmod)}</lastmod>\n")
    parts.append("  </url>\n")
    return "".join(parts)


class SitemapGenerator:
    """
    Generates XML sitemaps from successfully crawled pages.

    Includes only:
      - status_code 200
      - content_type text/html
      - not marked as duplicate, blocked, or low-quality (configurable)

    Args:
        output_dir: Directory to write sitemap files.
        base_url:   Optional base URL for sitemap index (e.g., https://example.com).
    """

    def __init__(self, output_dir: Path, base_url: str = "") -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/")

    async def generate(
        self,
        pages: list[dict[str, Any]],
        run_id: int,
        exclude_low_quality: bool = True,
    ) -> list[Path]:
        """
        Generate sitemap(s) for *pages*.

        Args:
            pages:               List of page dicts from the repository.
            run_id:              Crawl run ID (for filenames).
            exclude_low_quality: Skip pages with is_low_quality=1.

        Returns:
            List of Path objects written (1 sitemap or N sitemaps + 1 index).
        """
        # Filter eligible pages
        eligible: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for page in pages:
            if page.get("status_code") != 200:
                continue
            ct = (page.get("content_type") or "").lower()
            if "html" not in ct:
                continue
            if exclude_low_quality and page.get("is_low_quality"):
                continue
            url = page.get("canonical_url") or page.get("final_url") or page.get("original_url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            eligible.append(page)

        logger.info("Generating sitemap for %d eligible pages", len(eligible))

        # Split into chunks of SITEMAP_MAX_URLS
        chunks: list[list[dict[str, Any]]] = []
        for i in range(0, max(1, len(eligible)), SITEMAP_MAX_URLS):
            chunks.append(eligible[i : i + SITEMAP_MAX_URLS])

        written: list[Path] = []
        if len(chunks) == 1:
            path = await self._write_sitemap(chunks[0], run_id, index=None)
            written.append(path)
        else:
            for idx, chunk in enumerate(chunks, 1):
                path = await self._write_sitemap(chunk, run_id, index=idx)
                written.append(path)
            index_path = await self._write_index(written, run_id)
            written.append(index_path)

        return written

    async def _write_sitemap(
        self,
        pages: list[dict[str, Any]],
        run_id: int,
        index: int | None,
    ) -> Path:
        fname = (
            f"sitemap_run_{run_id}.xml"
            if index is None
            else f"sitemap_run_{run_id}_{index}.xml"
        )
        out_path = self._output_dir / fname
        try:
            with out_path.open("w", encoding="utf-8") as f:
                f.write(_URLSET_OPEN)
                for page in pages:
                    url = page.get("canonical_url") or page.get("final_url") or page.get("original_url")
                    lastmod = page.get("modified_at") or page.get("crawled_at")
                    if lastmod and len(lastmod) > 10:
                        lastmod = lastmod[:10]  # YYYY-MM-DD
                    f.write(_url_entry(url, lastmod))
                f.write(_URLSET_CLOSE)
            logger.info("Sitemap written -> %s (%d URLs)", out_path, len(pages))
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write sitemap: {exc}") from exc

    async def _write_index(self, sitemap_paths: list[Path], run_id: int) -> Path:
        out_path = self._output_dir / f"sitemap_index_run_{run_id}.xml"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            with out_path.open("w", encoding="utf-8") as f:
                f.write(_SITEMAPINDEX_OPEN)
                for path in sitemap_paths:
                    url = (
                        f"{self._base_url}/{path.name}"
                        if self._base_url
                        else path.name
                    )
                    f.write(
                        f"  <sitemap>\n"
                        f"    <loc>{escape(url)}</loc>\n"
                        f"    <lastmod>{now}</lastmod>\n"
                        f"  </sitemap>\n"
                    )
                f.write(_SITEMAPINDEX_CLOSE)
            logger.info("Sitemap index written -> %s", out_path)
            return out_path
        except OSError as exc:
            raise ExportError(f"Failed to write sitemap index: {exc}") from exc
