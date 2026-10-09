"""
Intelligence/ollama_service.py
Ollama LLM provider implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp
from pydantic import ValidationError

from Intelligence.llm_service import LLMService
from Intelligence.models import PageIntelligence, RagAnswer
from Intelligence.pii_redactor import redact_pii
from Intelligence.prompts import (
    SYSTEM_PAGE_ANALYSIS,
    SYSTEM_RAG_QA,
    wrap_page_content,
    wrap_rag_context,
)
from Utilities.config import Settings
from Utilities.exceptions import LLMServiceError

logger = logging.getLogger(__name__)


class OllamaLLMService(LLMService):
    """
    Ollama-based LLM provider.

    Connects to a local Ollama instance (default: http://localhost:11434).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.llm_model
        self._session: aiohttp.ClientSession | None = None

    def is_enabled(self) -> bool:
        return True

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session

    async def _chat(self, system: str, user: str) -> str:
        """Send a chat request to Ollama and return the response content."""
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
        }
        start = time.monotonic()
        try:
            async with self._get_session().post(url, json=payload) as resp:
                if resp.status != 200:
                    raise LLMServiceError(
                        f"Ollama returned HTTP {resp.status}",
                        provider="ollama",
                        model=self._model,
                    )
                data = await resp.json()
                latency_ms = (time.monotonic() - start) * 1000
                content = data.get("message", {}).get("content", "")
                logger.info(
                    "Ollama call latency=%.0fms model=%s", latency_ms, self._model
                )
                return content
        except aiohttp.ClientError as exc:
            raise LLMServiceError(
                f"Ollama connection error: {exc}", provider="ollama"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise LLMServiceError(
                "Ollama call timed out", provider="ollama"
            ) from exc

    async def analyze_page(self, title: str, text: str) -> PageIntelligence:
        """Analyze a page with Ollama and return validated PageIntelligence."""
        if self._settings.llm_redact_pii:
            redaction = redact_pii(text)
            text = redaction.redacted_text

        user_prompt = wrap_page_content(title, text, self._settings.llm_max_input_chars)

        try:
            raw = await self._chat(SYSTEM_PAGE_ANALYSIS, user_prompt)
            parsed = json.loads(raw)
            return PageIntelligence.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, LLMServiceError) as exc:
            logger.warning("Page analysis failed: %s", exc)
            return PageIntelligence(summary="Analysis failed.")

    async def answer_question(
        self, question: str, context_chunks: list[dict[str, Any]]
    ) -> RagAnswer:
        """Answer a question using retrieved context."""
        if not context_chunks:
            return RagAnswer(
                answer="Insufficient evidence to answer this question.",
                sufficient_evidence=False,
            )

        user_prompt = wrap_rag_context(question, context_chunks)

        try:
            raw = await self._chat(SYSTEM_RAG_QA, user_prompt)
            parsed = json.loads(raw)
            answer = RagAnswer.model_validate(parsed)
            # Verify cited URLs are from retrieved set (prevent hallucination)
            valid_urls = {
                c.get("final_url") or c.get("original_url") for c in context_chunks
            }
            answer.citations = [
                cite for cite in answer.citations if cite.url in valid_urls
            ]
            return answer
        except (json.JSONDecodeError, ValidationError, LLMServiceError) as exc:
            logger.warning("RAG answer failed: %s", exc)
            return RagAnswer(
                answer="Insufficient evidence to answer this question.",
                sufficient_evidence=False,
            )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
