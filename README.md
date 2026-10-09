# CrawlMind

> Responsible Async Web Crawler and LLM-Assisted Data Intelligence Engine

**CrawlMind** is a production-grade, asynchronous Python web crawler designed with a strict focus on ethical crawling, robust architecture, SSRF security, and extensible AI (LLM & RAG) capabilities.

It was built as an internship project demonstrating advanced system design, asynchronous networking, and AI integration.

## 🌟 Key Features

*   **High-Performance Async Engine:** Built on `asyncio` and `aiohttp` for concurrent, non-blocking fetching.
*   **Ethical & Polite:** Honors `robots.txt` (with wildcard support via `protego`) and implements per-domain rate limiting and `Crawl-delay`.
*   **SSRF Protection:** Built-in defenses against DNS-rebinding and Server-Side Request Forgery by validating all IPs post-DNS resolution.
*   **Resumable:** Uses an SQLite WAL database to persist state, allowing interrupted crawls to be resumed seamlessly.
*   **Full-Text Search (FTS5):** Instant search over crawled content using SQLite's native FTS5 extension.
*   **Data Intelligence (Optional LLM):** Can pass crawled content to local (Ollama) or external LLMs for summarization, named entity extraction, classification, and RAG (Retrieval-Augmented Generation) question answering.
*   **Green Crawling:** Supports conditional GET requests (`ETag` and `Last-Modified`) to save bandwidth on unchanged pages.
*   **PII Redaction:** Strips emails, phone numbers, and API tokens before sending data to external LLM providers.
*   **Export Options:** Export crawl data to JSON, CSV, and XML Sitemaps.

## 🏗 Architecture Overview

The system strictly follows Hexagonal Architecture (Ports and Adapters) principles:

1.  **Crawler:** The orchestration layer (queue management, fetching, policy evaluation).
2.  **Parser:** Pure, stateless HTML extraction (BeautifulSoup/lxml).
3.  **Exporter:** Persistence and search (SQLite, FTS5, JSON/CSV exports).
4.  **Intelligence (Optional):** PII redaction and LLM integrations (Ollama, OpenAI-compatible).
5.  **Utilities:** Configuration, logging, SSRF guards, and CLI.

*See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed breakdown and data flow diagram.*

## 🚀 Quick Start

### 1. Prerequisites

*   Python 3.11+
*   *(Optional)* Docker and Docker Compose

### 2. Installation

```bash
git clone https://github.com/yourusername/crawlmind.git
cd crawlmind
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configuration

Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` to configure your settings (e.g., max depth, concurrency, timeouts).

### 4. Basic Usage

Start a crawl from a seed URL:
```bash
python main.py crawl --url https://example.com --max-depth 2
```

Search the crawled pages:
```bash
python main.py search "example keyword"
```

Export data:
```bash
python main.py export 1 -f json -o output/
```

Ask a question (Requires LLM configured):
```bash
python main.py ask "What is the main topic of the site?"
```

## 🔒 Security Model

CrawlMind treats the open internet as an untrusted source.

*   **URL Validation:** Blocks `file://`, `ftp://`, `data:`, `javascript:`, and userinfo (`user:pass@host`).
*   **SSRF Guard (SafeResolver):** Custom `aiohttp` resolver that verifies IPs against private/loopback/metadata CIDRs *after* DNS resolution to prevent DNS-rebinding attacks.
*   **Prompt Injection Defense:** Web content is wrapped in `<untrusted_document>` tags and is never placed in the LLM's `system` prompt.

*See [SECURITY.md](SECURITY.md) for full details.*

## 🧪 Testing

The project has comprehensive test coverage using `pytest` and `pytest-asyncio`. Tests do not hit the live internet (responses are mocked using `aioresponses`).

```bash
pip install -r requirements-dev.txt
pytest
```

## 🐳 Docker

Run the entire stack in an isolated container:

```bash
docker build -t crawlmind .
docker run --rm -it -v $(pwd)/data:/app/data crawlmind crawl --url https://example.com
```

Or using docker-compose:
```bash
docker-compose up -d
```

## 📚 Documentation

*   [Architecture Details](ARCHITECTURE.md)
*   [Security Guidelines](SECURITY.md)
*   [API Reference](API.md)
*   [Contributing Guide](CONTRIBUTING.md)
*   [Changelog](CHANGELOG.md)

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
