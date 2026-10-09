"""
Exporter/migrations.py
Versioned SQLite schema migrations for CrawlMind.

Uses a schema_version table to track applied migrations.
Each migration is a list of SQL statements.
"""

from __future__ import annotations

import logging
from typing import Callable

import aiosqlite

from Utilities.constants import SCHEMA_VERSION

logger = logging.getLogger(__name__)

# Each migration is identified by its target version number.
# Migrations are applied in order from current_version+1 to SCHEMA_VERSION.
_MIGRATIONS: dict[int, list[str]] = {
    1: [
        # ── Core tables ────────────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """,
        "INSERT INTO schema_version (version) VALUES (0)",
        """
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at   TEXT    NOT NULL,
            finished_at  TEXT,
            status       TEXT    NOT NULL CHECK(status IN ('running','completed','interrupted','failed')),
            seeds_json   TEXT    NOT NULL,
            config_json  TEXT    NOT NULL,
            user_agent   TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS urls (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
            url           TEXT    NOT NULL,
            domain        TEXT    NOT NULL,
            depth         INTEGER NOT NULL,
            parent_url    TEXT,
            priority      INTEGER NOT NULL DEFAULT 0,
            retry_count   INTEGER NOT NULL DEFAULT 0,
            status        TEXT    NOT NULL CHECK(status IN (
                'queued','processing','success','failed','skipped',
                'blocked_by_robots','blocked_by_security','duplicate'
            )),
            discovered_at TEXT    NOT NULL,
            updated_at    TEXT    NOT NULL,
            UNIQUE(run_id, url)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_urls_run_status ON urls(run_id, status)",
        """
        CREATE TABLE IF NOT EXISTS pages (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            url_id              INTEGER NOT NULL UNIQUE REFERENCES urls(id) ON DELETE CASCADE,
            run_id              INTEGER NOT NULL REFERENCES crawl_runs(id),
            original_url        TEXT    NOT NULL,
            final_url           TEXT    NOT NULL,
            canonical_url       TEXT,
            status_code         INTEGER NOT NULL,
            content_type        TEXT,
            content_length      INTEGER,
            response_time_ms    REAL,
            depth               INTEGER NOT NULL,
            language            TEXT,
            title               TEXT,
            meta_description    TEXT,
            author              TEXT,
            published_at        TEXT,
            modified_at         TEXT,
            headings_json       TEXT,
            paragraphs_json     TEXT,
            cleaned_text        TEXT,
            word_count          INTEGER,
            reading_time_min    REAL,
            quality_score       REAL,
            is_low_quality      INTEGER DEFAULT 0,
            content_hash        TEXT    NOT NULL,
            response_hash       TEXT,
            etag                TEXT,
            last_modified       TEXT,
            headers_json        TEXT,
            raw_html            BLOB,
            parser_version      TEXT    NOT NULL,
            extraction_version  TEXT    NOT NULL,
            crawled_at          TEXT    NOT NULL,
            bytes_downloaded    INTEGER,
            bytes_saved         INTEGER DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pages_hash ON pages(content_hash)",
        "CREATE INDEX IF NOT EXISTS idx_pages_run  ON pages(run_id, depth)",
        """
        CREATE TABLE IF NOT EXISTS links (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
            target_url  TEXT    NOT NULL,
            anchor_text TEXT,
            is_internal INTEGER NOT NULL,
            rel         TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS images (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
            src     TEXT    NOT NULL,
            alt     TEXT,
            width   INTEGER,
            height  INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS metadata (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
            kind    TEXT    NOT NULL CHECK(kind IN ('meta','open_graph','twitter','json_ld','media')),
            key     TEXT,
            value   TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS crawl_errors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER NOT NULL REFERENCES crawl_runs(id),
            url           TEXT    NOT NULL,
            error_type    TEXT    NOT NULL,
            error_message TEXT,
            http_status   INTEGER,
            retry_count   INTEGER,
            occurred_at   TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS keyword_frequency (
            run_id        INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
            term          TEXT    NOT NULL,
            frequency     INTEGER NOT NULL,
            doc_frequency INTEGER NOT NULL,
            PRIMARY KEY(run_id, term)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id       INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
            task          TEXT    NOT NULL,
            model         TEXT    NOT NULL,
            result_json   TEXT    NOT NULL,
            input_hash    TEXT    NOT NULL,
            pii_redacted  INTEGER NOT NULL,
            latency_ms    REAL,
            tokens_in     INTEGER,
            tokens_out    INTEGER,
            created_at    TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS page_changes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT    NOT NULL,
            old_page_id INTEGER REFERENCES pages(id),
            new_page_id INTEGER NOT NULL REFERENCES pages(id),
            old_hash    TEXT,
            new_hash    TEXT,
            change_score REAL,
            added_text  TEXT,
            removed_text TEXT,
            llm_summary TEXT,
            detected_at TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES crawl_runs(id),
            event       TEXT    NOT NULL,
            url         TEXT,
            detail      TEXT,
            occurred_at TEXT    NOT NULL
        )
        """,
        # ── FTS5 virtual table (contentless — no text duplication) ────────────
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            title,
            headings,
            paragraphs,
            cleaned_text,
            content='',
            tokenize='porter unicode61 remove_diacritics 2'
        )
        """,
    ],
    2: [
        # Add meta_keywords column (added in schema v2)
        "ALTER TABLE pages ADD COLUMN meta_keywords TEXT",
    ],
    3: [
        # Add twitter_card columns
        "ALTER TABLE pages ADD COLUMN og_title TEXT",
        "ALTER TABLE pages ADD COLUMN og_description TEXT",
        "ALTER TABLE pages ADD COLUMN og_image TEXT",
        "ALTER TABLE pages ADD COLUMN og_type TEXT",
        "ALTER TABLE pages ADD COLUMN og_url TEXT",
        "ALTER TABLE pages ADD COLUMN twitter_title TEXT",
        "ALTER TABLE pages ADD COLUMN twitter_description TEXT",
        "ALTER TABLE pages ADD COLUMN twitter_image TEXT",
        "ALTER TABLE pages ADD COLUMN twitter_card TEXT",
    ],
}


async def run_migrations(db: aiosqlite.Connection) -> None:
    """
    Apply any pending migrations to *db*.

    Idempotent: safe to call on every startup.
    """
    # Create schema_version if it doesn't exist yet
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    await db.commit()

    row = await (await db.execute("SELECT version FROM schema_version")).fetchone()
    current = row[0] if row else 0

    if current >= SCHEMA_VERSION:
        logger.debug("DB schema up-to-date (v%d)", current)
        return

    logger.info("Running migrations from v%d -> v%d", current, SCHEMA_VERSION)
    for version in range(current + 1, SCHEMA_VERSION + 1):
        stmts = _MIGRATIONS.get(version, [])
        for stmt in stmts:
            try:
                await db.execute(stmt.strip())
            except Exception as exc:
                # ALTERs may fail if column already exists — ignore
                if "duplicate column" in str(exc).lower():
                    logger.debug("Skipping duplicate column migration: %s", exc)
                else:
                    raise
        await db.execute(
            "UPDATE schema_version SET version = ?", (version,)
        )
        await db.commit()
        logger.info("Applied migration v%d", version)
