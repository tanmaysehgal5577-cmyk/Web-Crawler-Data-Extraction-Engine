"""
Intelligence/content_classifier.py
Hook that runs LLM analysis on crawled pages and saves the result to DB.
"""

from __future__ import annotations

import logging
from typing import Any

from Crawler.crawler import PostPageProcessor
from Exporter.sqlite_repository import SQLiteRepository
from Intelligence.llm_service import LLMService
from Parser.models import ParsedPage

logger = logging.getLogger(__name__)


class LlmPostProcessor(PostPageProcessor):
    """
    PostPageProcessor hook that sends crawled content to LLM for analysis,
    then saves the resulting PageIntelligence JSON to the llm_results table.
    """

    def __init__(
        self,
        llm: LLMService,
        db: SQLiteRepository,
        model_name: str,
        pii_redacted: bool,
    ) -> None:
        self._llm = llm
        self._db = db
        self._model = model_name
        self._pii_redacted = pii_redacted

    async def process(self, page: ParsedPage, page_id: int, run_id: int) -> None:
        """Analyze page and persist result."""
        if not self._llm.is_enabled():
            return
            
        if not page.cleaned_text or len(page.cleaned_text) < 50:
            return

        try:
            import time
            start = time.monotonic()
            
            intelligence = await self._llm.analyze_page(
                title=page.title or "Untitled",
                text=page.cleaned_text,
            )
            
            latency = (time.monotonic() - start) * 1000
            
            # Save to DB
            await self._db._conn().execute(
                """
                INSERT INTO llm_results
                    (page_id, task, model, result_json, input_hash, pii_redacted, latency_ms, tokens_in, tokens_out, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    page_id,
                    "analyze_page",
                    self._model,
                    intelligence.model_dump_json(),
                    page.content_hash,
                    int(self._pii_redacted),
                    latency,
                    0, 0
                )
            )
            await self._db._conn().commit()
            
        except Exception as exc:
            logger.warning("LLM PostProcessor failed for page_id=%d: %s", page_id, exc)
