"""
Utilities/logging_config.py
Structured logging setup for CrawlMind.

Supports two formats:
  - json    : machine-readable JSON lines (production / CI)
  - console : human-readable coloured output (development)

Run-ID and URL are stored in contextvars so they propagate automatically
through asyncio tasks without manual passing.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ── Context variables (set per-task, auto-inherited by child tasks) ───────────

_ctx_run_id: ContextVar[str] = ContextVar("run_id", default="")
_ctx_url: ContextVar[str] = ContextVar("url", default="")
_ctx_domain: ContextVar[str] = ContextVar("domain", default="")


def set_log_context(
    run_id: str = "",
    url: str = "",
    domain: str = "",
) -> None:
    """Set per-task log context (call at the start of each worker task)."""
    if run_id:
        _ctx_run_id.set(run_id)
    if url:
        _ctx_url.set(url)
    if domain:
        _ctx_domain.set(domain)


def get_log_context() -> dict[str, str]:
    """Return current context dict for injection into log records."""
    return {
        "run_id": _ctx_run_id.get(),
        "url": _ctx_url.get(),
        "domain": _ctx_domain.get(),
    }


# ── JSON formatter ─────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A002
        ctx = get_log_context()
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "run_id": ctx["run_id"] or getattr(record, "run_id", ""),
            "url": ctx["url"] or getattr(record, "url", ""),
            "domain": ctx["domain"] or getattr(record, "domain", ""),
        }
        # Optional fields attached via logger.info("msg", extra={...})
        for key in ("status_code", "depth", "retry", "duration_ms", "error_type"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc"] = record.exc_text

        # Stack trace only at DEBUG
        if record.levelno == logging.DEBUG and record.stack_info:
            payload["stack"] = record.stack_info

        return json.dumps(payload, ensure_ascii=False)


# ── Console formatter (coloured) ──────────────────────────────────────────────

_LEVEL_COLOURS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
}
_RESET = "\033[0m"


class _ConsoleFormatter(logging.Formatter):
    """Human-readable coloured console output."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A002
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        ctx = get_log_context()
        run_part = f"[{ctx['run_id'][:8]}] " if ctx["run_id"] else ""
        url_part = f" {ctx['url']}" if ctx["url"] else ""

        msg = f"{colour}{ts} {record.levelname:<8}{_RESET} {run_part}{record.getMessage()}{url_part}"

        if record.exc_info:
            msg += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return msg


# ── Public API ─────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO", fmt: str = "json") -> None:
    """
    Configure root logger for CrawlMind.

    Args:
        level: Logging level string (DEBUG / INFO / WARNING / ERROR).
        fmt:   Output format – 'json' or 'console'.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    if fmt.lower() == "console":
        handler.setFormatter(_ConsoleFormatter())
    else:
        handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any existing handlers (avoid duplicate lines in pytest)
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("aiohttp", "asyncio", "urllib3", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
