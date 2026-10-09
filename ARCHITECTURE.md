# Architecture Details

CrawlMind uses a Hexagonal Architecture (Ports and Adapters) pattern to decouple the core business logic from infrastructure concerns.

## Directory Structure & Modules

*   **`main.py`**: Thin entry point that triggers the Typer CLI.
*   **`Utilities/` (Cross-cutting Concerns)**:
    *   `config.py`: Environment variable validation (`pydantic` equivalent using `dataclasses`).
    *   `security.py`: SSRF guards and custom `SafeResolver` for `aiohttp`.
    *   `logging_config.py`: Structured JSON logging with `contextvars`.
    *   `cli.py`: Command-line interface definitions using Typer.
*   **`Crawler/` (Core Logic)**:
    *   `crawler.py`: Orchestrates the producer-consumer workflow (Frontier -> Workers -> Parser -> DB Writer).
    *   `fetcher.py`: Performs async HTTP requests using `aiohttp` (redirect handling, chunked reading).
    *   `rate_limiter.py`: Manages global and per-domain concurrency using `asyncio.Semaphore`.
    *   `robots_manager.py`: Parses and caches `robots.txt` rules using `protego`.
*   **`Parser/` (Data Extraction)**:
    *   `html_parser.py`: Pure, stateless extraction using `BeautifulSoup`.
    *   `content_cleaner.py`: Strips boilerplate (nav, footer, ads) to extract readable text.
    *   `metadata_parser.py`: Extracts JSON-LD, Open Graph, and standard meta tags.
*   **`Exporter/` (Persistence)**:
    *   `sqlite_repository.py`: Async SQLite database handler using `aiosqlite` with WAL mode.
    *   `search_service.py`: Implements FTS5 (Full-Text Search) over crawled pages.
    *   `sitemap_generator.py`: Generates XML sitemaps chunked by URL count.
*   **`Intelligence/` (AI / LLM Layer)**:
    *   `llm_service.py`: Interface for LLM integrations (Ollama, OpenAI).
    *   `rag_service.py`: Retrieval-Augmented Generation using FTS5 search.
    *   `pii_redactor.py`: Redacts sensitive data before LLM processing.

## Concurrency Model

CrawlMind uses a hybrid concurrency model:

1.  **I/O Bound (Fetching):** Handled by `asyncio` tasks and `aiohttp`. N workers continuously pull URLs from an `asyncio.PriorityQueue`.
2.  **CPU Bound (Parsing):** HTML parsing is delegated to a `ThreadPoolExecutor` to prevent blocking the async event loop.
3.  **Database Writes:** A single, dedicated `db_writer` task reads parsed pages from a queue and persists them to SQLite sequentially. This prevents SQLite WAL "database is locked" errors that often occur with high concurrent writes.

## Data Flow Diagram

```text
User CLI -> CrawlEngine.run()
               |
               v
      +-------------------+
      | CrawlFrontier     | <-- (Priority Queue)
      +-------------------+
               |
         (N async workers)
               |
               v
      +-------------------+
      | UrlPolicy Check   | -> (Skip if depth/domain invalid)
      +-------------------+
               |
               v
      +-------------------+
      | Robots.txt Check  | -> (Skip if disallowed)
      +-------------------+
               |
               v
      +-------------------+
      | Rate Limiter      | -> (Wait on Semaphore)
      +-------------------+
               |
               v
      +-------------------+
      | Fetcher (aiohttp) | -> (Handle HTTP redirects, conditional GET)
      +-------------------+
               |
               v
      +-------------------+
      | Parser (bs4)      | -> (Run in ThreadPoolExecutor)
      +-------------------+
               |
               v
      +-------------------+
      | Result Queue      |
      +-------------------+
               |
         (Single task)
               |
               v
      +-------------------+
      | SQLite Repository | -> (Insert Page, update FTS5, extract links)
      +-------------------+
               |
               v
      +-------------------+
      | Intelligence Hook | -> (Optional LLM classification)
      +-------------------+
```
