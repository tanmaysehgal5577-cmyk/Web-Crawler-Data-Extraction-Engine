"""
Utilities/container.py
Dependency Injection (Composition Root) for CrawlMind.
"""

from __future__ import annotations

from typing import Optional

from Utilities.config import Settings
from Intelligence.llm_service import LLMService, DisabledLLMService


def build_llm_service(settings: Settings) -> LLMService:
    """Factory for the configured LLMService."""
    if not settings.enable_llm or settings.llm_provider == "disabled":
        return DisabledLLMService()
        
    if settings.llm_provider == "ollama":
        from Intelligence.ollama_service import OllamaLLMService
        return OllamaLLMService(settings)
        
    if settings.llm_provider == "openai_compatible":
        from Intelligence.openai_compatible_service import OpenAICompatibleLLMService
        return OpenAICompatibleLLMService(settings)
        
    return DisabledLLMService()
