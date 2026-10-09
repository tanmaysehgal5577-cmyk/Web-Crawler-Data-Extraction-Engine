"""
Parser/models.py
Data models for the parser layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Link:
    """A hyperlink extracted from a page."""

    url: str
    anchor_text: str
    is_internal: bool
    rel: str = ""


@dataclass
class Image:
    """An image extracted from a page."""

    src: str
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ParsedPage:
    """
    Complete structured data extracted from one HTML page.
    All fields that may be absent are Optional with None default.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    original_url: str
    final_url: str
    canonical_url: Optional[str] = None
    status_code: int = 200
    content_type: str = ""
    content_length: int = 0
    response_time_ms: float = 0.0
    depth: int = 0

    # ── Basic metadata ────────────────────────────────────────────────────────
    title: Optional[str] = None
    meta_description: Optional[str] = None
    meta_keywords: Optional[str] = None
    language: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    modified_at: Optional[str] = None

    # ── Open Graph ────────────────────────────────────────────────────────────
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    og_type: Optional[str] = None
    og_url: Optional[str] = None

    # ── Twitter Card ──────────────────────────────────────────────────────────
    twitter_title: Optional[str] = None
    twitter_description: Optional[str] = None
    twitter_image: Optional[str] = None
    twitter_card: Optional[str] = None

    # ── Structure ─────────────────────────────────────────────────────────────
    headings: dict[str, list[str]] = field(default_factory=dict)   # h1-h6 → [text]
    paragraphs: list[str] = field(default_factory=list)
    cleaned_text: str = ""
    word_count: int = 0
    reading_time_min: float = 0.0

    # ── Links & Media ─────────────────────────────────────────────────────────
    internal_links: list[Link] = field(default_factory=list)
    external_links: list[Link] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)

    # ── JSON-LD ───────────────────────────────────────────────────────────────
    json_ld: list[dict] = field(default_factory=list)

    # ── Hashes & quality ──────────────────────────────────────────────────────
    content_hash: str = ""          # SHA-256 of cleaned_text
    response_hash: Optional[str] = None    # SHA-256 of raw bytes
    is_low_quality: bool = False
    quality_score: float = 1.0

    # ── Provenance ────────────────────────────────────────────────────────────
    etag: Optional[str] = None
    last_modified_header: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    raw_html: Optional[bytes] = None

    # ── Versioning ────────────────────────────────────────────────────────────
    parser_version: str = ""
    extraction_version: str = ""
    crawled_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
