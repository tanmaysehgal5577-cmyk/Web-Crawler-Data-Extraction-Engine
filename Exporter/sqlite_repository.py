"""
Exporter/sqlite_repository.py
SQLite storage layer for CrawlMind.

Design:
  - Single DB-writer task pattern: all writes go through a single aiosqlite
    connection to avoid WAL locking issues with concurrent asyncio tasks.
  - WAL mode + foreign keys enabled on every connection.
  - FTS5 index populated on insert via explicit INSERT INTO pages_fts.
  - Repository pattern: callers use abstract interface, not SQL directly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from Crawler.models import UrlStatus
from Exporter.migrations import run_migrations
from Parser.models import ParsedPage
from Utilities.exceptions import StorageError

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """
    Async SQLite storage with WAL mode.

    All public methods are coroutines.
    Use as an async context manager or call open()/close() manually.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def open(self) -> None:
        """Open database connection and apply migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row

        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA cache_size=-64000")   # 64 MB page cache
        await run_migrations(self._db)
        logger.info("SQLite database opened: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "SQLiteRepository":
        await self.open()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _conn(self) -> aiosqlite.Connection:
        if not self._db:
            raise StorageError("Database is not open. Call open() first.")
        return self._db

    # ── Crawl runs ─────────────────────────────────────────────────────────────

    async def create_crawl_run(
        self,
        seeds: list[str],
        config: dict[str, Any],
        user_agent: str,
    ) -> int:
        """Insert a new crawl run and return its ID."""
        cursor = await self._conn().execute(
            """
            INSERT INTO crawl_runs (started_at, status, seeds_json, config_json, user_agent)
            VALUES (?, 'running', ?, ?, ?)
            """,
            (_now(), json.dumps(seeds), json.dumps(config), user_agent),
        )
        await self._conn().commit()
        run_id = cursor.lastrowid
        logger.info("Created crawl run #%d", run_id)
        return run_id  # type: ignore[return-value]

    async def finish_crawl_run(self, run_id: int, status: str = "completed") -> None:
        """Update a crawl run's status and finished_at timestamp."""
        await self._conn().execute(
            "UPDATE crawl_runs SET status=?, finished_at=? WHERE id=?",
            (status, _now(), run_id),
        )
        await self._conn().commit()

    async def get_crawl_run(self, run_id: int) -> Optional[dict[str, Any]]:
        """Return crawl run metadata, or None if not found."""
        cursor = await self._conn().execute(
            "SELECT * FROM crawl_runs WHERE id=?", (run_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_crawl_runs(self) -> list[dict[str, Any]]:
        """Return all crawl runs ordered by start time descending."""
        cursor = await self._conn().execute(
            "SELECT * FROM crawl_runs ORDER BY started_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── URLs ───────────────────────────────────────────────────────────────────

    async def upsert_url(
        self,
        run_id: int,
        url: str,
        domain: str,
        depth: int,
        status: UrlStatus,
        parent_url: Optional[str] = None,
        priority: int = 0,
        retry_count: int = 0,
    ) -> int:
        """
        Insert or update a URL record.

        Returns:
            URL row ID.
        """
        now = _now()
        cursor = await self._conn().execute(
            """
            INSERT INTO urls
                (run_id, url, domain, depth, parent_url, priority, retry_count,
                 status, discovered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, url) DO UPDATE SET
                status=excluded.status,
                retry_count=excluded.retry_count,
                updated_at=excluded.updated_at
            """,
            (run_id, url, domain, depth, parent_url, priority,
             retry_count, status.value, now, now),
        )
        await self._conn().commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_url_id(self, run_id: int, url: str) -> Optional[int]:
        """Return the urls.id for a given run + URL."""
        cursor = await self._conn().execute(
            "SELECT id FROM urls WHERE run_id=? AND url=?", (run_id, url)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_urls_by_status(self, run_id: int, status: UrlStatus) -> list[dict]:
        """Return all URL rows for a given status (used for resume)."""
        cursor = await self._conn().execute(
            "SELECT * FROM urls WHERE run_id=? AND status=?",
            (run_id, status.value),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def hash_exists(self, content_hash: str) -> bool:
        """Return True if this content hash already exists (duplicate detection)."""
        cursor = await self._conn().execute(
            "SELECT 1 FROM pages WHERE content_hash=? LIMIT 1", (content_hash,)
        )
        return (await cursor.fetchone()) is not None

    # ── Pages ──────────────────────────────────────────────────────────────────

    async def insert_page(
        self,
        run_id: int,
        url_id: int,
        page: ParsedPage,
        bytes_downloaded: int = 0,
        bytes_saved: int = 0,
    ) -> int:
        """
        Insert a parsed page and update FTS5 index.

        Returns:
            pages.id of the inserted row.
        """
        headings_json = json.dumps(page.headings)
        paragraphs_json = json.dumps(page.paragraphs[:200])  # cap for storage

        cursor = await self._conn().execute(
            """
            INSERT INTO pages (
                url_id, run_id, original_url, final_url, canonical_url,
                status_code, content_type, content_length, response_time_ms,
                depth, language, title, meta_description, meta_keywords, author,
                published_at, modified_at, headings_json, paragraphs_json,
                cleaned_text, word_count, reading_time_min, quality_score, is_low_quality,
                content_hash, response_hash, etag, last_modified, headers_json,
                raw_html, parser_version, extraction_version, crawled_at,
                bytes_downloaded, bytes_saved,
                og_title, og_description, og_image, og_type, og_url,
                twitter_title, twitter_description, twitter_image, twitter_card
            ) VALUES (
                ?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,?,
                ?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?
            )
            """,
            (
                url_id, run_id, page.original_url, page.final_url, page.canonical_url,
                page.status_code, page.content_type, page.content_length, page.response_time_ms,
                page.depth, page.language, page.title, page.meta_description,
                page.meta_keywords, page.author,
                page.published_at, page.modified_at,
                headings_json, paragraphs_json,
                page.cleaned_text, page.word_count, page.reading_time_min,
                page.quality_score, int(page.is_low_quality),
                page.content_hash, page.response_hash, page.etag,
                page.last_modified_header, json.dumps(page.headers),
                page.raw_html, page.parser_version, page.extraction_version, page.crawled_at,
                bytes_downloaded, bytes_saved,
                page.og_title, page.og_description, page.og_image, page.og_type, page.og_url,
                page.twitter_title, page.twitter_description, page.twitter_image, page.twitter_card,
            ),
        )
        page_id = cursor.lastrowid

        # ── FTS5 index ──────────────────────────────────────────────────────
        headings_text = " ".join(
            h for hs in page.headings.values() for h in hs
        )
        paragraphs_text = " ".join(page.paragraphs[:50])
        await self._conn().execute(
            """
            INSERT INTO pages_fts(rowid, title, headings, paragraphs, cleaned_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                page_id,
                page.title or "",
                headings_text,
                paragraphs_text,
                page.cleaned_text or "",
            ),
        )

        # ── Links ───────────────────────────────────────────────────────────
        link_rows = [
            (page_id, lnk.url, lnk.anchor_text, int(lnk.is_internal), lnk.rel)
            for lnk in (page.internal_links + page.external_links)
        ]
        if link_rows:
            await self._conn().executemany(
                "INSERT INTO links (page_id, target_url, anchor_text, is_internal, rel) "
                "VALUES (?,?,?,?,?)",
                link_rows,
            )

        # ── Images ──────────────────────────────────────────────────────────
        img_rows = [
            (page_id, img.src, img.alt, img.width, img.height)
            for img in page.images
        ]
        if img_rows:
            await self._conn().executemany(
                "INSERT INTO images (page_id, src, alt, width, height) VALUES (?,?,?,?,?)",
                img_rows,
            )

        await self._conn().commit()
        return page_id  # type: ignore[return-value]

    async def get_page(self, page_id: int) -> Optional[dict[str, Any]]:
        """Return a page row by ID."""
        cursor = await self._conn().execute(
            "SELECT * FROM pages WHERE id=?", (page_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_page_by_url(self, run_id: int, url: str) -> Optional[dict[str, Any]]:
        """Return a page row by run + URL."""
        cursor = await self._conn().execute(
            """
            SELECT p.* FROM pages p
            JOIN urls u ON u.id = p.url_id
            WHERE u.run_id=? AND u.url=?
            """,
            (run_id, url),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_pages(
        self,
        run_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return pages for a crawl run."""
        cursor = await self._conn().execute(
            "SELECT * FROM pages WHERE run_id=? ORDER BY id LIMIT ? OFFSET ?",
            (run_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_successful_pages(self, run_id: int) -> int:
        """Return count of successful pages for a run."""
        cursor = await self._conn().execute(
            "SELECT COUNT(*) FROM urls WHERE run_id=? AND status='success'",
            (run_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Errors ─────────────────────────────────────────────────────────────────

    async def insert_error(
        self,
        run_id: int,
        url: str,
        error_type: str,
        error_message: str,
        http_status: Optional[int] = None,
        retry_count: int = 0,
    ) -> None:
        """Persist a crawl error."""
        await self._conn().execute(
            """
            INSERT INTO crawl_errors
                (run_id, url, error_type, error_message, http_status, retry_count, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, url, error_type, error_message, http_status, retry_count, _now()),
        )
        await self._conn().commit()

    async def list_errors(self, run_id: int) -> list[dict[str, Any]]:
        """Return all errors for a crawl run."""
        cursor = await self._conn().execute(
            "SELECT * FROM crawl_errors WHERE run_id=? ORDER BY occurred_at",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Audit events ───────────────────────────────────────────────────────────

    async def insert_audit_event(
        self,
        run_id: Optional[int],
        event: str,
        url: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Log a security or robots block event."""
        await self._conn().execute(
            "INSERT INTO audit_events (run_id, event, url, detail, occurred_at) VALUES (?,?,?,?,?)",
            (run_id, event, url, detail, _now()),
        )
        await self._conn().commit()

    # ── Keyword frequency ──────────────────────────────────────────────────────

    async def upsert_keyword_frequency(
        self,
        run_id: int,
        term_counts: dict[str, int],
        doc_frequency: dict[str, int],
    ) -> None:
        """Bulk upsert keyword frequency data."""
        rows = [
            (run_id, term, count, doc_frequency.get(term, 1))
            for term, count in term_counts.items()
        ]
        await self._conn().executemany(
            """
            INSERT INTO keyword_frequency (run_id, term, frequency, doc_frequency)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id, term) DO UPDATE SET
                frequency=frequency+excluded.frequency,
                doc_frequency=doc_frequency+excluded.doc_frequency
            """,
            rows,
        )
        await self._conn().commit()

    async def get_top_keywords(self, run_id: int, top_n: int = 50) -> list[dict]:
        """Return top-N keywords by frequency for a crawl run."""
        cursor = await self._conn().execute(
            """
            SELECT term, frequency, doc_frequency
            FROM keyword_frequency
            WHERE run_id=?
            ORDER BY frequency DESC
            LIMIT ?
            """,
            (run_id, top_n),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Page changes ───────────────────────────────────────────────────────────

    async def insert_page_change(
        self,
        url: str,
        old_page_id: Optional[int],
        new_page_id: int,
        old_hash: Optional[str],
        new_hash: str,
        change_score: float,
        added_text: str,
        removed_text: str,
    ) -> None:
        """Record a content change between two crawls of the same URL."""
        await self._conn().execute(
            """
            INSERT INTO page_changes
                (url, old_page_id, new_page_id, old_hash, new_hash,
                 change_score, added_text, removed_text, detected_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (url, old_page_id, new_page_id, old_hash, new_hash,
             change_score, added_text, removed_text, _now()),
        )
        await self._conn().commit()

    async def get_page_changes(self, url: str) -> list[dict]:
        """Return all recorded changes for a URL."""
        cursor = await self._conn().execute(
            "SELECT * FROM page_changes WHERE url=? ORDER BY detected_at DESC",
            (url,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
