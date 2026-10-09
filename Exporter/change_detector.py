"""
Exporter/change_detector.py
Content change detection between two crawls of the same URL.
"""

from __future__ import annotations

import difflib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_change(
    old_text: str,
    new_text: str,
) -> tuple[float, str, str]:
    """
    Compute change score and diff between old and new page text.

    Args:
        old_text: Previous version's cleaned text.
        new_text: Current version's cleaned text.

    Returns:
        (change_score, added_text, removed_text)
        change_score: 0.0 = identical, 1.0 = completely different.
    """
    if old_text == new_text:
        return 0.0, "", ""

    # Use SequenceMatcher for similarity
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
    similarity = matcher.ratio()
    change_score = round(1.0 - similarity, 4)

    # Extract added and removed lines
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    added_lines: list[str] = []
    removed_lines: list[str] = []

    for group in matcher.get_grouped_opcodes(n=3):
        for tag, i1, i2, j1, j2 in group:
            if tag in ("replace", "delete"):
                removed_lines.extend(old_lines[i1:i2])
            if tag in ("replace", "insert"):
                added_lines.extend(new_lines[j1:j2])

    added_text = "".join(added_lines)[:5000]    # cap for storage
    removed_text = "".join(removed_lines)[:5000]

    return change_score, added_text, removed_text
