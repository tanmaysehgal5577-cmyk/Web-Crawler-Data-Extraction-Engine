# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-08

### Added
*   **M1: Foundational Framework**
    *   Configuration management via environment variables (with validation).
    *   Custom exception hierarchy.
    *   Rich-based CLI statistics reporting.
    *   JSON-structured contextual logging using `contextvars`.
*   **M2: URL & Security Layer**
    *   Robust URL normalization (tracking parameter removal, domain extraction).
    *   URL evaluation policy (depth, traps, extensions).
    *   Anti-SSRF guard (`SafeResolver`) blocking private IPs and DNS rebinding.
*   **M3: Core Crawl Engine**
    *   Async producer-consumer architecture using `asyncio` and `aiohttp`.
    *   `RobotsManager` honoring `robots.txt` rules and crawl delays via `protego`.
    *   Exponential backoff and retry policies.
    *   Concurrency control using nested `asyncio.Semaphore` (global and per-domain).
    *   Resumable Priority Queue.
*   **M4: Extraction & Parsing**
    *   BeautifulSoup/lxml based stateless HTML parser.
    *   Boilerplate removal and quality scoring.
    *   Metadata extraction (Open Graph, Twitter Cards, JSON-LD).
*   **M5: Data Export & Storage**
    *   SQLite repository with WAL mode and schema migrations.
    *   JSON and CSV export capabilities.
    *   XML Sitemap generator with index support for >50k URLs.
    *   Content change detection via `difflib.SequenceMatcher`.
*   **M6: Applied Search & NLP**
    *   FTS5-powered full-text search with BM25 ranking.
    *   Term frequency and document frequency analytics.
*   **M7: LLM & RAG Integration**
    *   PII redaction engine (Regex/Hashing).
    *   Extensible LLM Service interface (Ollama & OpenAI-compatible support).
    *   RAG service for natural language querying over crawled data with strict citation enforcement.
    *   Post-processing hooks for automated page intelligence and classification.
