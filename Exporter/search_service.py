"""
Exporter/search_service.py
FTS5-powered full-text search and keyword frequency analysis.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import aiosqlite

from Utilities.constants import FTS5_STOPWORDS

logger = logging.getLogger(__name__)

_SPECIAL_CHARS = re.compile(r'["\*\(\)\{\}\[\]\^\\]')


def _sanitize_query(query: str) -> str:
    """
    Sanitize user query for FTS5 MATCH expression.
    Escapes special FTS5 operators to prevent query injection.
    """
    return _SPECIAL_CHARS.sub(" ", query).strip()


class SearchService:
    """
    Full-text search over the pages_fts FTS5 virtual table.

    Args:
        db: Open aiosqlite connection.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def search(
        self,
        query: str,
        run_id: Optional[int] = None,
        domain: Optional[str] = None,
        depth: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Search for pages matching *query*.

        Supports:
          - Phrase queries: "exact phrase"
          - Boolean AND (default between terms)
          - Domain filter, run filter, depth filter

        Args:
            query:  Search query string.
            run_id: Limit to a specific crawl run.
            domain: Limit to a specific domain.
            depth:  Limit to a specific crawl depth.
            limit:  Max results to return.
            offset: Pagination offset.

        Returns:
            List of page dicts with rank score added.
        """
        sanitized = _sanitize_query(query)
        if not sanitized:
            return []

        # Build WHERE clause
        where_parts = ["pages_fts MATCH ?"]
        params: list[Any] = [sanitized]

        join = "JOIN pages p ON pages_fts.rowid = p.id"
        extra_where: list[str] = []

        if run_id is not None:
            extra_where.append("p.run_id = ?")
            params.append(run_id)
        if domain is not None:
            extra_where.append("p.final_url LIKE ?")
            params.append(f"%://{domain}%")
        if depth is not None:
            extra_where.append("p.depth = ?")
            params.append(depth)

        extra_clause = ""
        if extra_where:
            extra_clause = "AND " + " AND ".join(extra_where)

        sql = f"""
            SELECT
                p.*,
                bm25(pages_fts, 10.0, 5.0, 2.0, 1.0) AS rank
            FROM pages_fts
            {join}
            WHERE {where_parts[0]}
            {extra_clause}
            ORDER BY rank
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        try:
            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("FTS5 search error for query %r: %s", query, exc)
            return []

    async def get_keyword_frequency(
        self,
        run_id: int,
        top_n: int = 50,
        min_freq: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Return top keywords by frequency for a crawl run.

        Filters out stopwords and very short terms.

        Args:
            run_id:   Crawl run ID.
            top_n:    Maximum number of keywords to return.
            min_freq: Minimum term frequency to include.

        Returns:
            List of {term, frequency, doc_frequency} dicts.
        """
        cursor = await self._db.execute(
            """
            SELECT term, frequency, doc_frequency
            FROM keyword_frequency
            WHERE run_id=? AND frequency >= ? AND length(term) > 2
            ORDER BY frequency DESC
            LIMIT ?
            """,
            (run_id, min_freq, top_n),
        )
        rows = await cursor.fetchall()
        # Filter stopwords
        return [
            dict(r) for r in rows
            if r["term"].lower() not in FTS5_STOPWORDS
        ]

    async def compute_keyword_frequency(
        self,
        run_id: int,
    ) -> dict[str, int]:
        """
        Compute keyword frequency across all pages in a run.
        Stores results in keyword_frequency table.

        Returns:
            {term: total_frequency} dict.
        """
        cursor = await self._db.execute(
            "SELECT cleaned_text FROM pages WHERE run_id=?", (run_id,)
        )
        rows = await cursor.fetchall()

        from collections import Counter
        total: Counter[str] = Counter()
        doc_freq: Counter[str] = Counter()

        for row in rows:
            text = (row[0] or "").lower()
            words = re.findall(r"[a-z]{3,}", text)
            filtered = [w for w in words if w not in FTS5_STOPWORDS]
            page_terms = set(filtered)
            total.update(filtered)
            doc_freq.update(page_terms)

        # Bulk insert
        if total:
            await self._db.executemany(
                """
                INSERT INTO keyword_frequency (run_id, term, frequency, doc_frequency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, term) DO UPDATE SET
                    frequency=excluded.frequency,
                    doc_frequency=excluded.doc_frequency
                """,
                [(run_id, term, count, doc_freq[term]) for term, count in total.items()],
            )
            await self._db.commit()

        return dict(total)
