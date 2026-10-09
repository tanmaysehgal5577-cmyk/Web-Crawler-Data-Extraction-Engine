# API Reference

While CrawlMind is primarily a CLI application, it can be used programmatically as a Python library.

## Core Modules

### `Utilities.config`

*   `load_settings()`: Loads and validates configuration from the environment and `.env` file into a `Settings` dataclass.

### `Crawler.crawler`

*   `class CrawlEngine(settings, repository, post_processors)`
    *   `async run(seed_urls: list[str], resume_run_id: int | None = None) -> CrawlResult`: Starts or resumes a crawl. Returns a dataclass containing `run_id`, `status`, and dictionary of `stats`.

### `Exporter.sqlite_repository`

*   `class SQLiteRepository(db_path: Path)`
    *   Async context manager that handles database connection, WAL mode initialization, and migrations.
    *   `async get_page(page_id: int)`: Retrieve parsed page data.
    *   `async list_pages(run_id: int, limit: int)`: List crawled pages.
    *   `async get_page_changes(url: str)`: Get historical changes for a specific URL across crawls.

### `Parser.html_parser`

*   `class HtmlParser()`
    *   `parse(fetch_result: FetchResult, store_raw_html: bool) -> ParsedPage`: Pure function that extracts links, text, headings, and metadata from an HTML payload.

### `Intelligence.llm_service`

*   `class LLMService` (ABC)
    *   `async analyze_page(title: str, text: str) -> PageIntelligence`
    *   `async answer_question(question: str, context_chunks: list[dict]) -> RagAnswer`

### `Intelligence.rag_service`

*   `class RagService(db, llm, run_id, top_k)`
    *   `async ask(question: str) -> RagAnswer`: Performs FTS5 BM25 search, packages results into a prompt, and queries the LLM for an answer.

## Data Models

Located in `Crawler.models` and `Parser.models`.

### `ParsedPage`
The main artifact of the system, containing:
*   `original_url`, `final_url`, `canonical_url`
*   `status_code`, `content_type`, `content_length`, `response_time_ms`
*   `title`, `meta_description`, `author`, `published_at`
*   `headings`, `paragraphs`, `cleaned_text`, `word_count`
*   `internal_links`, `external_links`, `images`, `json_ld`
*   `content_hash` (SHA-256 for change detection)
*   Open Graph and Twitter Card data

## Extensibility (Post-Processors)

You can write custom hooks to process pages as they are crawled by implementing the `PostPageProcessor` protocol and passing it to `CrawlEngine`.

```python
from Crawler.crawler import PostPageProcessor
from Parser.models import ParsedPage

class MyCustomHook(PostPageProcessor):
    async def process(self, page: ParsedPage, page_id: int, run_id: int) -> None:
        if "Machine Learning" in page.cleaned_text:
            print(f"Found ML content on {page.final_url}")
```
