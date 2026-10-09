"""
Parser/metadata_parser.py
Extracts Open Graph, Twitter Card, JSON-LD, canonical, dates, and author.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common date meta name variants
_DATE_META_NAMES = {
    "article:published_time", "article:modified_time",
    "date", "pubdate", "publish_date", "publication_date",
    "lastmod", "last-modified", "og:updated_time",
    "datePublished", "dateModified",
}


def extract_og(soup: BeautifulSoup) -> dict[str, str]:
    """Extract all Open Graph meta properties."""
    og: dict[str, str] = {}
    for tag in soup.find_all("meta", property=re.compile(r"^og:")):
        prop = tag.get("property", "").replace("og:", "").replace(":", "_")
        content = tag.get("content", "")
        if prop and content:
            og[prop] = content
    return og


def extract_twitter(soup: BeautifulSoup) -> dict[str, str]:
    """Extract all Twitter Card meta tags."""
    tw: dict[str, str] = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
        name = tag.get("name", "").replace("twitter:", "").replace(":", "_")
        content = tag.get("content", "")
        if name and content:
            tw[name] = content
    return tw


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extract and parse all JSON-LD script blocks."""
    results: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict):
                results.append(data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("JSON-LD parse error: %s", exc)
    return results


def extract_canonical(soup: BeautifulSoup) -> Optional[str]:
    """Extract canonical URL from <link rel='canonical'>."""
    tag = soup.find("link", rel="canonical")
    if tag:
        href = tag.get("href", "")  # type: ignore[union-attr]
        return str(href).strip() if href else None
    return None


def extract_language(soup: BeautifulSoup) -> Optional[str]:
    """Extract page language from <html lang='...'>."""
    html_tag = soup.find("html")
    if html_tag:
        lang = html_tag.get("lang", "")  # type: ignore[union-attr]
        return str(lang).strip() or None
    return None


def extract_dates(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """
    Return (published_date, modified_date) from meta tags and JSON-LD.
    """
    published: Optional[str] = None
    modified: Optional[str] = None

    # Check all meta tags
    for tag in soup.find_all("meta"):
        name = (tag.get("name") or tag.get("property") or "").lower()
        content = tag.get("content", "")
        if not content:
            continue
        if name in {"article:published_time", "date", "pubdate", "publish_date",
                    "publication_date", "datepublished"}:
            published = published or content
        elif name in {"article:modified_time", "lastmod", "last-modified",
                      "og:updated_time", "datemodified"}:
            modified = modified or content

    # Check time tags
    time_tag = soup.find("time", datetime=True)
    if time_tag and not published:
        published = time_tag.get("datetime")  # type: ignore[assignment]

    return published, modified


def extract_author(soup: BeautifulSoup) -> Optional[str]:
    """Extract author from meta or common microdata patterns."""
    # <meta name="author">
    tag = soup.find("meta", attrs={"name": re.compile(r"author", re.I)})
    if tag:
        return str(tag.get("content", "")).strip() or None

    # JSON-LD author
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                author = data.get("author")
                if isinstance(author, dict):
                    return str(author.get("name", "")).strip() or None
                if isinstance(author, str):
                    return author.strip() or None
        except Exception:
            pass

    # Common class-based patterns
    for cls in ["author", "byline", "entry-author"]:
        el = soup.find(class_=re.compile(cls, re.I))
        if el:
            text = el.get_text(strip=True)
            if text:
                return text[:200]

    return None
