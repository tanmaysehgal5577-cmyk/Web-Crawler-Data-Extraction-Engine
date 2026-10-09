"""
Intelligence/llm_service.py
Abstract LLM service and disabled (no-op) implementation.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from Intelligence.models import PageIntelligence, RagAnswer

logger = logging.getLogger(__name__)


class LLMService(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def analyze_page(self, title: str, text: str) -> PageIntelligence:
        """Summarize and classify a page."""

    @abstractmethod
    async def answer_question(
        self, question: str, context_chunks: list[dict[str, Any]]
    ) -> RagAnswer:
        """Answer a question given retrieved context chunks."""

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True if this provider is actually configured."""


class DisabledLLMService(LLMService):
    """
    No-op LLM service used when LLM is disabled.
    Returns empty/default responses without making any network calls.
    """

    def is_enabled(self) -> bool:
        return False

    async def analyze_page(self, title: str, text: str) -> PageIntelligence:
        return PageIntelligence()

    async def answer_question(
        self, question: str, context_chunks: list[dict[str, Any]]
    ) -> RagAnswer:
        return RagAnswer(
            answer="LLM is disabled. Enable with CRAWLER_ENABLE_LLM=true.",
            sufficient_evidence=False,
            citations=[],
        )
