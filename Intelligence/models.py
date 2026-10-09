"""
Intelligence/models.py
Pydantic output schemas for LLM-generated content.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class PageIntelligence(BaseModel):
    """Validated LLM output for page analysis."""

    summary: str = Field(default="", max_length=500)
    topics: list[str] = Field(default_factory=list, max_length=10)
    category: str = Field(default="", max_length=100)
    named_entities: list[str] = Field(default_factory=list, max_length=30)
    technologies: list[str] = Field(default_factory=list, max_length=20)
    important_keywords: list[str] = Field(default_factory=list, max_length=20)
    quality_note: Optional[str] = Field(default=None, max_length=200)


class Citation(BaseModel):
    """A source citation for a RAG answer."""

    url: str
    title: Optional[str] = None
    crawled_at: str
    content_hash: str
    excerpt: Optional[str] = None


class RagAnswer(BaseModel):
    """Validated LLM output for RAG question answering."""

    answer: str = Field(default="Insufficient evidence to answer this question.")
    sufficient_evidence: bool = False
    citations: list[Citation] = Field(default_factory=list)
