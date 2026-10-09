"""
Utilities/config.py
Settings dataclass loaded from environment / .env file.
Every value is validated at startup; invalid config raises ConfigurationError.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from Utilities.exceptions import ConfigurationError

# Load .env file if present (does not override real env vars)
load_dotenv(dotenv_path=Path(".env"), override=False)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key, str(default)).lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{key} must be a boolean (true/false), got: {val!r}")


def _env_int(key: str, default: int, min_val: int = 1, max_val: int = 10_000) -> int:
    raw = _env(key, str(default))
    try:
        val = int(raw)
    except ValueError:
        raise ConfigurationError(f"{key} must be an integer, got: {raw!r}") from None
    if not (min_val <= val <= max_val):
        raise ConfigurationError(f"{key} must be between {min_val} and {max_val}, got: {val}")
    return val


def _env_float(
    key: str,
    default: float,
    min_val: float = 0.0,
    max_val: float = 3600.0,
) -> float:
    raw = _env(key, str(default))
    try:
        val = float(raw)
    except ValueError:
        raise ConfigurationError(f"{key} must be a float, got: {raw!r}") from None
    if not (min_val <= val <= max_val):
        raise ConfigurationError(f"{key} must be between {min_val} and {max_val}, got: {val}")
    return val


def _env_list(key: str, default: str = "") -> list[str]:
    raw = _env(key, default)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """
    All runtime configuration for CrawlMind.
    Loaded once at startup and treated as immutable.
    """

    # ── Identity ───────────────────────────────────────────────────────────────
    user_agent: str
    respect_robots_txt: bool
    robots_failure_policy: Literal["allow_all", "deny_all", "allow_on_404_deny_on_error"]
    default_delay_seconds: float

    # ── Scope ──────────────────────────────────────────────────────────────────
    max_depth: int
    max_pages: int
    allowed_domains: list[str]
    max_url_length: int
    max_query_params: int
    follow_redirects: bool
    max_redirects: int

    # ── Concurrency ────────────────────────────────────────────────────────────
    global_concurrency: int
    per_domain_concurrency: int

    # ── Timeouts & Retries ─────────────────────────────────────────────────────
    request_timeout_seconds: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_retries: int
    base_retry_delay_seconds: float
    max_retry_delay_seconds: float
    max_response_bytes: int

    # ── Storage ────────────────────────────────────────────────────────────────
    database_path: Path
    output_directory: Path
    store_raw_html: bool
    log_level: str
    log_format: Literal["json", "console"]

    # ── Security ───────────────────────────────────────────────────────────────
    allowlist_mode: bool
    block_private_networks: bool

    # ── Optional features ──────────────────────────────────────────────────────
    enable_js_rendering: bool
    js_render_domains: list[str]
    enable_llm: bool
    enable_mcp: bool

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: Literal["disabled", "ollama", "openai_compatible"]
    llm_model: str
    ollama_base_url: str
    openai_base_url: str
    openai_api_key: str
    llm_max_input_chars: int
    llm_max_output_tokens: int
    llm_redact_pii: bool
    llm_allow_external: bool

    # ── Derived helpers (not in __init__) ─────────────────────────────────────

    def is_domain_allowed(self, domain: str) -> bool:
        """Return True if domain is in the allowed set (or set is empty)."""
        if not self.allowed_domains:
            return True
        return domain in self.allowed_domains

    def __repr__(self) -> str:
        # Never leak the API key
        return (
            f"Settings(user_agent={self.user_agent!r}, max_depth={self.max_depth}, "
            f"max_pages={self.max_pages}, global_concurrency={self.global_concurrency}, "
            f"llm_provider={self.llm_provider!r}, ...)"
        )


def load_settings() -> Settings:
    """
    Build and validate a Settings instance from environment variables.

    Raises:
        ConfigurationError: On any invalid or inconsistent value.
    """
    # Identity
    user_agent = _env("CRAWLER_USER_AGENT", "CrawlMind/1.0")
    if not user_agent:
        raise ConfigurationError("CRAWLER_USER_AGENT must not be empty")

    robots_policy_raw = _env(
        "CRAWLER_ROBOTS_FAILURE_POLICY", "allow_on_404_deny_on_error"
    )
    valid_policies = {"allow_all", "deny_all", "allow_on_404_deny_on_error"}
    if robots_policy_raw not in valid_policies:
        raise ConfigurationError(
            f"CRAWLER_ROBOTS_FAILURE_POLICY must be one of {valid_policies}, "
            f"got: {robots_policy_raw!r}"
        )

    # Scope
    max_depth = _env_int("CRAWLER_MAX_DEPTH", 2, min_val=0, max_val=50)
    max_pages = _env_int("CRAWLER_MAX_PAGES", 100, min_val=1, max_val=1_000_000)

    # Concurrency
    global_concurrency = _env_int("CRAWLER_GLOBAL_CONCURRENCY", 10, min_val=1, max_val=500)
    per_domain_concurrency = _env_int(
        "CRAWLER_PER_DOMAIN_CONCURRENCY", 2, min_val=1, max_val=100
    )
    if per_domain_concurrency > global_concurrency:
        raise ConfigurationError(
            "CRAWLER_PER_DOMAIN_CONCURRENCY must be ≤ CRAWLER_GLOBAL_CONCURRENCY, "
            f"got {per_domain_concurrency} > {global_concurrency}"
        )

    # Timeouts
    connect_timeout = _env_float("CRAWLER_CONNECT_TIMEOUT_SECONDS", 10.0, 1.0, 120.0)
    read_timeout = _env_float("CRAWLER_READ_TIMEOUT_SECONDS", 20.0, 1.0, 300.0)
    request_timeout = _env_float("CRAWLER_REQUEST_TIMEOUT_SECONDS", 30.0, 1.0, 600.0)
    if connect_timeout > request_timeout:
        raise ConfigurationError(
            "CRAWLER_CONNECT_TIMEOUT_SECONDS must be ≤ CRAWLER_REQUEST_TIMEOUT_SECONDS"
        )

    base_retry = _env_float("CRAWLER_BASE_RETRY_DELAY_SECONDS", 1.0, 0.0, 60.0)
    max_retry = _env_float("CRAWLER_MAX_RETRY_DELAY_SECONDS", 60.0, 0.0, 3600.0)
    if base_retry > max_retry:
        raise ConfigurationError(
            "CRAWLER_BASE_RETRY_DELAY_SECONDS must be ≤ CRAWLER_MAX_RETRY_DELAY_SECONDS"
        )

    # Log format
    log_format_raw = _env("CRAWLER_LOG_FORMAT", "json").lower()
    if log_format_raw not in {"json", "console"}:
        raise ConfigurationError(
            f"CRAWLER_LOG_FORMAT must be 'json' or 'console', got: {log_format_raw!r}"
        )

    # LLM provider
    llm_provider_raw = _env("LLM_PROVIDER", "disabled").lower()
    valid_providers = {"disabled", "ollama", "openai_compatible"}
    if llm_provider_raw not in valid_providers:
        raise ConfigurationError(
            f"LLM_PROVIDER must be one of {valid_providers}, got: {llm_provider_raw!r}"
        )

    enable_llm = _env_bool("CRAWLER_ENABLE_LLM", False)
    llm_allow_external = _env_bool("LLM_ALLOW_EXTERNAL", False)

    # Prevent accidental external LLM calls
    if enable_llm and llm_provider_raw == "openai_compatible" and not llm_allow_external:
        openai_base = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
        localhost_prefixes = ("http://localhost", "http://127.", "http://[::1]")
        if not any(openai_base.startswith(p) for p in localhost_prefixes):
            raise ConfigurationError(
                "LLM_ALLOW_EXTERNAL=false but OPENAI_BASE_URL points to a remote host. "
                "Set LLM_ALLOW_EXTERNAL=true to permit external LLM calls."
            )

    return Settings(
        user_agent=user_agent,
        respect_robots_txt=_env_bool("CRAWLER_RESPECT_ROBOTS_TXT", True),
        robots_failure_policy=robots_policy_raw,  # type: ignore[arg-type]
        default_delay_seconds=_env_float("CRAWLER_DEFAULT_DELAY_SECONDS", 1.0, 0.0, 60.0),
        max_depth=max_depth,
        max_pages=max_pages,
        allowed_domains=_env_list("CRAWLER_ALLOWED_DOMAINS"),
        max_url_length=_env_int("CRAWLER_MAX_URL_LENGTH", 2048, 50, 8192),
        max_query_params=_env_int("CRAWLER_MAX_QUERY_PARAMS", 10, 0, 100),
        follow_redirects=_env_bool("CRAWLER_FOLLOW_REDIRECTS", True),
        max_redirects=_env_int("CRAWLER_MAX_REDIRECTS", 5, 0, 30),
        global_concurrency=global_concurrency,
        per_domain_concurrency=per_domain_concurrency,
        request_timeout_seconds=request_timeout,
        connect_timeout_seconds=connect_timeout,
        read_timeout_seconds=read_timeout,
        max_retries=_env_int("CRAWLER_MAX_RETRIES", 3, 0, 20),
        base_retry_delay_seconds=base_retry,
        max_retry_delay_seconds=max_retry,
        max_response_bytes=_env_int(
            "CRAWLER_MAX_RESPONSE_BYTES", 5 * 1024 * 1024, 1024, 100 * 1024 * 1024
        ),
        database_path=Path(_env("CRAWLER_DATABASE_PATH", "data/crawlmind.db")),
        output_directory=Path(_env("CRAWLER_OUTPUT_DIRECTORY", "output")),
        store_raw_html=_env_bool("CRAWLER_STORE_RAW_HTML", False),
        log_level=_env("CRAWLER_LOG_LEVEL", "INFO").upper(),
        log_format=log_format_raw,  # type: ignore[arg-type]
        allowlist_mode=_env_bool("CRAWLER_ALLOWLIST_MODE", False),
        block_private_networks=_env_bool("CRAWLER_BLOCK_PRIVATE_NETWORKS", True),
        enable_js_rendering=_env_bool("CRAWLER_ENABLE_JS_RENDERING", False),
        js_render_domains=_env_list("CRAWLER_JS_RENDER_DOMAINS"),
        enable_llm=enable_llm,
        enable_mcp=_env_bool("CRAWLER_ENABLE_MCP", False),
        llm_provider=llm_provider_raw,  # type: ignore[arg-type]
        llm_model=_env("LLM_MODEL", "llama3.1"),
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=_env("OPENAI_API_KEY", ""),
        llm_max_input_chars=_env_int("LLM_MAX_INPUT_CHARS", 8000, 100, 128_000),
        llm_max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", 512, 16, 8192),
        llm_redact_pii=_env_bool("LLM_REDACT_PII", True),
        llm_allow_external=llm_allow_external,
    )
