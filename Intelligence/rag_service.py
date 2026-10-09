"""
Intelligence/rag_service.py
RAG (Retrieval-Augmented Generation) question answering.

Flow:
  1. FTS5 retrieval from local DB (bm25 ranking)
  2. (Optional) embedding-based re-ranking
  3. Context budget trimming
  4. PII redaction
  5. LLM answer with citations
  6. Citation URL verification (only retrieved URLs allowed)
  7. "Insufficient evidence" if not enough context
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import aiosqlite

from Exporter.search_service import SearchService
from Intelligence.llm_service import LLMService
from Intelligence.models import RagAnswer

logger = logging.getLogger(__name__)

_MIN_CONTEXT_WORDS = 50   # below this, we don't call the LLM


class RagService:
    """
    Retrieval-Augmented Generation question answering.

    Args:
        db:          Open aiosqlite connection.
        llm:         LLM service (may be DisabledLLMService).
        run_id:      Crawl run to search within.
        top_k:       Number of chunks to retrieve.
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        llm: LLMService,
        run_id: Optional[int] = None,
        top_k: int = 5,
    ) -> None:
        self._search = SearchService(db)
        self._llm = llm
        self._run_id = run_id
        self._top_k = top_k

    async def ask(self, question: str) -> RagAnswer:
        """
        Answer *question* using retrieved page content.

        Args:
            question: Natural language question.

        Returns:
            RagAnswer with answer, citations, and evidence flag.
        """
        if not self._llm.is_enabled():
            return RagAnswer(
                answer="LLM is disabled. Enable with CRAWLER_ENABLE_LLM=true.",
                sufficient_evidence=False,
            )

        # Retrieve relevant chunks
        chunks = await self._search.search(
            query=question,
            run_id=self._run_id,
            limit=self._top_k,
        )

        if not chunks:
            logger.info("RAG: no results for question: %r", question[:80])
            return RagAnswer(
                answer="Insufficient evidence to answer this question.",
                sufficient_evidence=False,
            )

        # Check minimum context
        total_words = sum(
            len((c.get("cleaned_text") or "").split()) for c in chunks
        )
        if total_words < _MIN_CONTEXT_WORDS:
            return RagAnswer(
                answer="Insufficient evidence to answer this question.",
                sufficient_evidence=False,
            )

        # Trim context to budget
        budget_chunks = self._trim_to_budget(chunks, max_chars=6000)

        logger.info(
            "RAG: retrieved %d chunks (%d words) for question: %r",
            len(budget_chunks),
            total_words,
            question[:80],
        )

        return await self._llm.answer_question(question, budget_chunks)

    def _trim_to_budget(
        self, chunks: list[dict[str, Any]], max_chars: int
    ) -> list[dict[str, Any]]:
        """Trim chunks to fit within max_chars total context."""
        result: list[dict[str, Any]] = []
        used = 0
        for chunk in chunks:
            text = chunk.get("cleaned_text") or ""
            if used + len(text) > max_chars:
                remaining = max_chars - used
                if remaining > 200:
                    trimmed = dict(chunk)
                    trimmed["cleaned_text"] = text[:remaining]
                    result.append(trimmed)
                break
            result.append(chunk)
            used += len(text)
        return result
