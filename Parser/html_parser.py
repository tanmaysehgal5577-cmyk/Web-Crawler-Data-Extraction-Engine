"""
Parser/html_parser.py
Main HTML parser orchestrator for CrawlMind.

Design:
  - Pure function (no I/O, no async) — safe to run in ThreadPoolExecutor
  - Uses BeautifulSoup with lxml backend
  - Extracts all required fields into ParsedPage
  - Handles malformed HTML gracefully
  - Computes SHA-256 content hash and reading time
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from Crawler.models import FetchResult
from Parser.content_cleaner import assess_quality, clean_html
from Parser.metadata_parser import (
    extract_author,
    extract_canonical,
    extract_dates,
    extract_json_ld,
    extract_language,
    extract_og,
    extract_twitter,
)
from Parser.models import Image, Link, ParsedPage
from Utilities.constants import EXTRACTION_VERSION, PARSER_VERSION

logger = logging.getLogger(__name__)

_WORDS_PER_MINUTE = 200   # average adult reading speed


class HtmlParser:
    """
    Stateless HTML parser.

    All methods are pure (no side effects, no I/O).
    """

    def parse(
        self,
        fetch_result: FetchResult,
        store_raw_html: bool = False,
    ) -> ParsedPage:
        """
        Parse HTML from *fetch_result* into a ParsedPage.

        Args:
            fetch_result:   Result of fetching a URL.
            store_raw_html: If True, store raw bytes in ParsedPage.raw_html.

        Returns:
            ParsedPage with all extracted fields.
        """
        raw = fetch_result.raw_bytes
        html_text = raw.decode("utf-8", errors="replace")

        try:
            soup = BeautifulSoup(html_text, "lxml")
        except Exception as exc:
            logger.warning("lxml parse failed, falling back to html.parser: %s", exc)
            try:
                soup = BeautifulSoup(html_text, "html.parser")
            except Exception as exc2:
                logger.error("Both parsers failed for %s: %s", fetch_result.url, exc2)
                return self._empty_page(fetch_result)

        # ── Basic metadata ──────────────────────────────────────────────────
        title = self._extract_title(soup)
        meta_desc = self._extract_meta(soup, "description")
        meta_keywords = self._extract_meta(soup, "keywords")
        canonical = extract_canonical(soup)
        language = extract_language(soup)
        author = extract_author(soup)
        published_at, modified_at = extract_dates(soup)

        # ── OG / Twitter / JSON-LD ──────────────────────────────────────────
        og = extract_og(soup)
        twitter = extract_twitter(soup)
        json_ld = extract_json_ld(soup)

        # ── Headings ─────────────────────────────────────────────────────────
        headings: dict[str, list[str]] = {}
        for level in ("h1", "h2", "h3", "h4", "h5", "h6"):
            texts = [
                t.get_text(strip=True)
                for t in soup.find_all(level)
                if t.get_text(strip=True)
            ]
            if texts:
                headings[level] = texts

        # ── Paragraphs ───────────────────────────────────────────────────────
        paragraphs: list[str] = [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 20
        ]

        # ── Cleaned text & stats ─────────────────────────────────────────────
        cleaned_text = clean_html(soup)
        words = cleaned_text.split()
        word_count = len(words)
        reading_time = round(word_count / _WORDS_PER_MINUTE, 2)

        # ── Content hash ─────────────────────────────────────────────────────
        content_hash = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()
        response_hash = hashlib.sha256(raw).hexdigest() if raw else None

        # ── Links ─────────────────────────────────────────────────────────────
        base = fetch_result.final_url
        internal_links, external_links = self._extract_links(soup, base)

        # ── Images ───────────────────────────────────────────────────────────
        images = self._extract_images(soup, base)

        # ── Quality ──────────────────────────────────────────────────────────
        has_heading = bool(headings)
        n_links = len(internal_links) + len(external_links)
        quality_score, is_low_quality = assess_quality(
            cleaned_text, word_count, n_links, has_heading
        )

        return ParsedPage(
            original_url=fetch_result.url,
            final_url=fetch_result.final_url,
            canonical_url=canonical,
            status_code=fetch_result.status_code,
            content_type=fetch_result.content_type,
            content_length=fetch_result.content_length,
            response_time_ms=fetch_result.response_time_ms,
            depth=fetch_result.depth,
            title=title,
            meta_description=meta_desc,
            meta_keywords=meta_keywords,
            language=language,
            author=author,
            published_at=published_at,
            modified_at=modified_at,
            og_title=og.get("title"),
            og_description=og.get("description"),
            og_image=og.get("image"),
            og_type=og.get("type"),
            og_url=og.get("url"),
            twitter_title=twitter.get("title"),
            twitter_description=twitter.get("description"),
            twitter_image=twitter.get("image"),
            twitter_card=twitter.get("card"),
            headings=headings,
            paragraphs=paragraphs,
            cleaned_text=cleaned_text,
            word_count=word_count,
            reading_time_min=reading_time,
            internal_links=internal_links,
            external_links=external_links,
            images=images,
            json_ld=json_ld,
            content_hash=content_hash,
            response_hash=response_hash,
            is_low_quality=is_low_quality,
            quality_score=quality_score,
            etag=fetch_result.etag,
            last_modified_header=fetch_result.last_modified,
            headers=fetch_result.headers,
            raw_html=raw if store_raw_html else None,
            parser_version=PARSER_VERSION,
            extraction_version=EXTRACTION_VERSION,
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            return text or None
        # Fallback: first h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True) or None
        return None

    def _extract_meta(self, soup: BeautifulSoup, name: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if tag:
            content = tag.get("content", "")  # type: ignore[union-attr]
            return str(content).strip() or None
        return None

    def _extract_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> tuple[list[Link], list[Link]]:
        """Extract and classify all <a href> links."""
        base_domain = (urlparse(base_url).hostname or "").lower().lstrip("www.")
        internal: list[Link] = []
        external: list[Link] = []

        seen: set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag.get("href", "")).strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            # Resolve relative URLs
            try:
                abs_url = urljoin(base_url, href).split("#")[0]
            except Exception:
                continue

            if abs_url in seen:
                continue
            seen.add(abs_url)

            parsed = urlparse(abs_url)
            if parsed.scheme not in ("http", "https"):
                continue

            anchor = a_tag.get_text(strip=True)[:200]
            rel = " ".join(a_tag.get("rel", []))

            link_domain = (parsed.hostname or "").lower().lstrip("www.")
            is_internal = link_domain == base_domain or link_domain.endswith("." + base_domain)

            link = Link(
                url=abs_url,
                anchor_text=anchor,
                is_internal=is_internal,
                rel=rel,
            )
            if is_internal:
                internal.append(link)
            else:
                external.append(link)

        return internal, external

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> list[Image]:
        """Extract <img> tags."""
        images: list[Image] = []
        for img in soup.find_all("img"):
            src = str(img.get("src", "") or img.get("data-src", "")).strip()
            if not src:
                continue
            try:
                abs_src = urljoin(base_url, src)
            except Exception:
                continue
            images.append(
                Image(
                    src=abs_src,
                    alt=str(img.get("alt", "")).strip(),
                    width=self._safe_int(img.get("width")),
                    height=self._safe_int(img.get("height")),
                )
            )
        return images

    def _safe_int(self, value: object) -> Optional[int]:
        try:
            return int(str(value))
        except (ValueError, TypeError):
            return None

    def _empty_page(self, fetch_result: FetchResult) -> ParsedPage:
        """Return a minimal ParsedPage when parsing completely fails."""
        return ParsedPage(
            original_url=fetch_result.url,
            final_url=fetch_result.final_url,
            status_code=fetch_result.status_code,
            content_type=fetch_result.content_type,
            content_length=fetch_result.content_length,
            response_time_ms=fetch_result.response_time_ms,
            depth=fetch_result.depth,
            content_hash=hashlib.sha256(b"").hexdigest(),
            is_low_quality=True,
            quality_score=0.0,
            headers=fetch_result.headers,
            parser_version=PARSER_VERSION,
            extraction_version=EXTRACTION_VERSION,
        )
