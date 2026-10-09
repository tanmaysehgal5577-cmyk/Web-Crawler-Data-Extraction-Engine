"""
Parser/content_cleaner.py
Removes boilerplate HTML elements to extract main readable text.

Strategy:
  - Remove script, style, nav, footer, header, aside, form, button elements
  - Remove common boilerplate class/id names (cookie banners, ads, menus)
  - Extract remaining text, collapse whitespace
  - Detect low-quality pages (too short, no headings, mostly links)
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag

# Tags whose content is never useful for reading
_REMOVE_TAGS = {
    "script", "style", "noscript", "template", "meta", "link",
    "nav", "footer", "header", "aside", "form", "button",
    "select", "option", "iframe", "embed", "object",
    "figure",  # kept unless it has a caption; simplified here
}

# CSS class/id fragments that suggest boilerplate
_BOILERPLATE_PATTERNS = re.compile(
    r"(cookie|banner|popup|modal|overlay|sidebar|advertisement|"
    r"ads?[-_]|menu|breadcrumb|pagination|social|share|subscribe|"
    r"newsletter|widget|related|recommend|comment|disqus|"
    r"navigation|navbar|topbar|toolbar)",
    re.IGNORECASE,
)

_MULTI_WHITESPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def clean_html(soup: BeautifulSoup) -> str:
    """
    Extract main text from a BeautifulSoup document.

    Modifies the soup in place (removes boilerplate elements).

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        Cleaned plain text string.
    """
    # Work on a copy to avoid side-effects on the caller's soup
    import copy
    soup = copy.copy(soup)

    # Remove boilerplate tags
    for tag_name in _REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements with boilerplate class/id names
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag) or getattr(tag, "attrs", None) is None:
            continue
        cls_val = tag.get("class", [])
        classes = " ".join(str(c) for c in cls_val) if isinstance(cls_val, list) else str(cls_val)
        tag_id = str(tag.get("id", ""))
        combined = f"{classes} {tag_id}"
        if _BOILERPLATE_PATTERNS.search(combined):
            tag.decompose()

    # Extract text
    text = soup.get_text(separator="\n")
    text = _MULTI_WHITESPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def assess_quality(
    cleaned_text: str,
    word_count: int,
    n_links: int,
    has_heading: bool,
) -> tuple[float, bool]:
    """
    Compute a quality score [0.0, 1.0] and a low-quality flag.

    Args:
        cleaned_text: Main page text.
        word_count:   Number of words in cleaned text.
        n_links:      Total internal + external links.
        has_heading:  Whether the page has at least one heading.

    Returns:
        (quality_score, is_low_quality)
    """
    score = 1.0

    if word_count < 50:
        score -= 0.4
    elif word_count < 100:
        score -= 0.2

    if not has_heading:
        score -= 0.15

    # Link-to-text ratio heuristic (mostly links → lower quality)
    if word_count > 0 and n_links > 0:
        ratio = n_links / word_count
        if ratio > 0.5:
            score -= 0.2
        elif ratio > 0.2:
            score -= 0.1

    score = max(0.0, min(1.0, score))
    is_low_quality = score < 0.4 or word_count < 20
    return round(score, 3), is_low_quality
