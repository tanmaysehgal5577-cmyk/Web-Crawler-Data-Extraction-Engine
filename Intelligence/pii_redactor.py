"""
Intelligence/pii_redactor.py
PII detection and redaction before sending content to external LLMs.

Detects and redacts:
  - Email addresses
  - Phone numbers (US/international formats)
  - API keys / tokens (long alphanumeric strings)
  - Credit card-like sequences
  - Bearer tokens
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# ── Patterns ───────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE)

_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s\-.]?)?"
    r"(?:\(\d{3}\)|\d{3})"
    r"[\s\-.]?\d{3}[\s\-.]?\d{4}"
    r"(?!\d)"
)

# Long random-looking strings (API keys, tokens) — 20+ hex/base64 chars
_TOKEN_RE = re.compile(r"(?<!\w)[A-Za-z0-9\-_]{20,}(?!\w)")

# Credit card: 4 groups of 4 digits (with separators)
_CC_RE = re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)")

# Bearer token in headers
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{10,}", re.IGNORECASE)


@dataclass
class RedactionResult:
    """Result of PII redaction."""

    redacted_text: str
    was_redacted: bool
    redaction_count: int


def redact_pii(text: str) -> RedactionResult:
    """
    Detect and redact PII from *text*.

    Redacted values are replaced with a hashed placeholder like [REDACTED:a1b2c3].
    The hash is deterministic, so the same value always maps to the same placeholder.

    Args:
        text: Input text to redact.

    Returns:
        RedactionResult with redacted text and stats.
    """
    count = 0
    result = text

    def _replace(match: re.Match, label: str) -> str:
        nonlocal count
        count += 1
        short_hash = hashlib.sha256(match.group().encode()).hexdigest()[:8]
        return f"[{label}:{short_hash}]"

    result = _EMAIL_RE.sub(lambda m: _replace(m, "EMAIL"), result)
    result = _BEARER_RE.sub(lambda m: _replace(m, "TOKEN"), result)
    result = _CC_RE.sub(lambda m: _replace(m, "CC"), result)
    result = _PHONE_RE.sub(lambda m: _replace(m, "PHONE"), result)
    # Token pattern last (broadest)
    result = _TOKEN_RE.sub(lambda m: _replace(m, "TOKEN"), result)

    return RedactionResult(
        redacted_text=result,
        was_redacted=count > 0,
        redaction_count=count,
    )
