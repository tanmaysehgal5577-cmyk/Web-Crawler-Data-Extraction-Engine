"""
Utilities/cli.py
Typer CLI commands for CrawlMind.

Commands:
  crawl    — Start or resume a crawl
  search   — Full-text search across crawled pages
  frequency — Show top keyword frequencies
  export   — Export data to JSON/CSV/SQLite/sitemap
  stats    — Show crawl run statistics
  changes  — Show content changes for a URL
  ask      — RAG question answering
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from Utilities.config import load_settings
from Utilities.exceptions import ConfigurationError
from Utilities.logging_config import setup_logging
from Utilities.validators import validate_seed_url

app = typer.Typer(
    name="crawlmind",
    help="CrawlMind — Responsible Async Web Crawler & LLM Intelligence Engine",
    add_completion=False,
)
console = Console()


def _get_settings():
    try:
        return load_settings()
    except ConfigurationError as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc


# ── crawl ──────────────────────────────────────────────────────────────────────

@app.command()
def crawl(
    url: list[str] = typer.Option([], "--url", "-u", help="Seed URL(s) to crawl"),
    url_file: Optional[Path] = typer.Option(None, "--url-file", help="File with one URL per line"),
    max_depth: Optional[int] = typer.Option(None, "--max-depth", help="Override max crawl depth"),
    max_pages: Optional[int] = typer.Option(None, "--max-pages", help="Override max page count"),
    allowed_domain: list[str] = typer.Option([], "--allowed-domain", help="Restrict to domain(s)"),
    resume: Optional[int] = typer.Option(None, "--resume", help="Resume crawl run ID"),
    no_robots: bool = typer.Option(False, "--no-robots", help="Disable robots.txt (unethical!)"),
    enable_llm: bool = typer.Option(False, "--enable-llm", help="Enable LLM analysis"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
) -> None:
    """Start a new crawl or resume an existing one."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)

    # Collect seed URLs
    seeds: list[str] = list(url)
    if url_file:
        try:
            for line in url_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    seeds.append(line)
        except OSError as exc:
            console.print(f"[red]Cannot read URL file: {exc}[/red]")
            raise typer.Exit(code=1) from exc

    if not seeds and not resume:
        console.print("[red]Provide at least one --url or --url-file[/red]")
        raise typer.Exit(code=1)

    # Validate seeds
    valid_seeds: list[str] = []
    for raw in seeds:
        try:
            valid_seeds.append(validate_seed_url(raw))
        except Exception as exc:
            console.print(f"[yellow]Skipping invalid URL {raw!r}: {exc}[/yellow]")

    if not valid_seeds and not resume:
        console.print("[red]No valid seed URLs.[/red]")
        raise typer.Exit(code=1)

    asyncio.run(_run_crawl(settings, valid_seeds, resume, output))


async def _run_crawl(settings, seeds, resume_run_id, output_dir):
    from Crawler.crawler import CrawlEngine
    from Exporter.sqlite_repository import SQLiteRepository

    if output_dir:
        settings = _override_output(settings, output_dir)

    async with SQLiteRepository(settings.database_path) as repo:
        engine = CrawlEngine(settings=settings, repository=repo)
        result = await engine.run(seed_urls=seeds, resume_run_id=resume_run_id)
        console.print(f"\n[bold green]Crawl completed![/bold green] Run ID: {result.run_id}")


def _override_output(settings, output_dir):
    """Create new settings with overridden output directory."""
    import os
    os.environ["CRAWLER_OUTPUT_DIRECTORY"] = str(output_dir)
    from Utilities.config import load_settings
    return load_settings()


# ── search ─────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    run_id: Optional[int] = typer.Option(None, "--run-id", help="Limit to crawl run"),
    domain: Optional[str] = typer.Option(None, "--domain", help="Limit to domain"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Search crawled pages using full-text search."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    asyncio.run(_run_search(settings, query, run_id, domain, limit))


async def _run_search(settings, query, run_id, domain, limit):
    import aiosqlite
    from Exporter.search_service import SearchService

    async with aiosqlite.connect(str(settings.database_path)) as db:
        db.row_factory = aiosqlite.Row
        svc = SearchService(db)
        results = await svc.search(query, run_id=run_id, domain=domain, limit=limit)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search results for '{query}'", show_lines=True)
    table.add_column("URL", style="cyan", overflow="fold", max_width=60)
    table.add_column("Title", max_width=40)
    table.add_column("Depth", justify="center")
    table.add_column("Score", justify="right")

    for r in results:
        table.add_row(
            r.get("final_url", "")[:60],
            (r.get("title") or "")[:40],
            str(r.get("depth", "")),
            f"{r.get('rank', 0):.3f}",
        )
    console.print(table)


# ── frequency ──────────────────────────────────────────────────────────────────

@app.command()
def frequency(
    run_id: int = typer.Argument(..., help="Crawl run ID"),
    top: int = typer.Option(30, "--top", "-n", help="Number of top keywords"),
) -> None:
    """Show keyword frequency analysis for a crawl run."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    asyncio.run(_run_frequency(settings, run_id, top))


async def _run_frequency(settings, run_id, top):
    import aiosqlite
    from Exporter.search_service import SearchService

    async with aiosqlite.connect(str(settings.database_path)) as db:
        db.row_factory = aiosqlite.Row
        svc = SearchService(db)
        # Compute if not yet available
        await svc.compute_keyword_frequency(run_id)
        keywords = await svc.get_keyword_frequency(run_id, top_n=top)

    if not keywords:
        console.print("[yellow]No keyword data. Run a crawl first.[/yellow]")
        return

    table = Table(title=f"Top {top} Keywords — Run #{run_id}")
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Term", style="cyan")
    table.add_column("Frequency", justify="right")
    table.add_column("Doc Freq", justify="right")

    for i, kw in enumerate(keywords, 1):
        table.add_row(str(i), kw["term"], str(kw["frequency"]), str(kw["doc_frequency"]))
    console.print(table)


# ── export ─────────────────────────────────────────────────────────────────────

@app.command()
def export(
    run_id: int = typer.Argument(..., help="Crawl run ID to export"),
    fmt: str = typer.Option("json", "--format", "-f", help="Format: json|csv|sitemap"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
) -> None:
    """Export crawl data to JSON, CSV, or sitemap."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    out_dir = output or settings.output_directory
    asyncio.run(_run_export(settings, run_id, fmt, out_dir))


async def _run_export(settings, run_id, fmt, out_dir):
    from Exporter.sqlite_repository import SQLiteRepository
    from Exporter.json_exporter import JsonExporter
    from Exporter.csv_exporter import CsvExporter
    from Exporter.sitemap_generator import SitemapGenerator

    out_dir = Path(out_dir)
    async with SQLiteRepository(settings.database_path) as repo:
        pages = await repo.list_pages(run_id, limit=100_000)
        errors = await repo.list_errors(run_id)

    if fmt == "json":
        exp = JsonExporter(out_dir)
        path = await exp.export_pages(pages, run_id)
        err_path = await JsonExporter(out_dir).export_stats(
            {"errors": errors}, run_id
        )
        console.print(f"[green]JSON exported -> {path}[/green]")

    elif fmt == "csv":
        exp = CsvExporter(out_dir)
        path = await exp.export_pages(pages, run_id)
        err_path = await exp.export_errors(errors, run_id)
        console.print(f"[green]CSV exported -> {path}[/green]")
        console.print(f"[green]Errors CSV -> {err_path}[/green]")

    elif fmt == "sitemap":
        gen = SitemapGenerator(out_dir)
        paths = await gen.generate(pages, run_id)
        for p in paths:
            console.print(f"[green]Sitemap -> {p}[/green]")
    else:
        console.print(f"[red]Unknown format: {fmt}. Use json|csv|sitemap[/red]")


# ── stats ──────────────────────────────────────────────────────────────────────

@app.command()
def stats(
    run_id: int = typer.Argument(..., help="Crawl run ID"),
) -> None:
    """Show statistics for a crawl run."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    asyncio.run(_run_stats(settings, run_id))


async def _run_stats(settings, run_id):
    from Exporter.sqlite_repository import SQLiteRepository

    async with SQLiteRepository(settings.database_path) as repo:
        run = await repo.get_crawl_run(run_id)
        if not run:
            console.print(f"[red]Run #{run_id} not found.[/red]")
            return

        successful = await repo.count_successful_pages(run_id)
        errors = await repo.list_errors(run_id)

    table = Table(title=f"Crawl Run #{run_id} Statistics")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", run.get("status", ""))
    table.add_row("Started At", run.get("started_at", ""))
    table.add_row("Finished At", run.get("finished_at") or "In progress")
    table.add_row("Seeds", run.get("seeds_json", "[]"))
    table.add_row("Pages Crawled", str(successful))
    table.add_row("Errors", str(len(errors)))
    console.print(table)


# ── changes ────────────────────────────────────────────────────────────────────

@app.command()
def changes(
    url: str = typer.Argument(..., help="URL to check for changes"),
) -> None:
    """Show content change history for a URL."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    asyncio.run(_run_changes(settings, url))


async def _run_changes(settings, url):
    from Exporter.sqlite_repository import SQLiteRepository

    async with SQLiteRepository(settings.database_path) as repo:
        history = await repo.get_page_changes(url)

    if not history:
        console.print(f"[yellow]No change history for {url}[/yellow]")
        return

    for change in history:
        console.print(f"\n[bold]Detected:[/bold] {change.get('detected_at')}")
        console.print(f"  Change score: {change.get('change_score', 0):.2%}")
        if change.get("added_text"):
            console.print(f"  [green]Added:[/green] {change['added_text'][:200]}")
        if change.get("removed_text"):
            console.print(f"  [red]Removed:[/red] {change['removed_text'][:200]}")


# ── ask ────────────────────────────────────────────────────────────────────────

@app.command()
def ask(
    question: str = typer.Argument(..., help="Question to answer"),
    run_id: Optional[int] = typer.Option(None, "--run-id", help="Limit to crawl run"),
    top_k: int = typer.Option(5, "--top-k", help="Number of context chunks"),
) -> None:
    """Ask a question using RAG over crawled content."""
    settings = _get_settings()
    setup_logging(settings.log_level, settings.log_format)
    asyncio.run(_run_ask(settings, question, run_id, top_k))


async def _run_ask(settings, question, run_id, top_k):
    import aiosqlite
    from Intelligence.llm_service import DisabledLLMService
    from Intelligence.rag_service import RagService

    if not settings.enable_llm:
        console.print("[yellow]LLM is disabled. Set CRAWLER_ENABLE_LLM=true[/yellow]")
        return

    # Build LLM service based on provider
    if settings.llm_provider == "ollama":
        from Intelligence.ollama_service import OllamaLLMService
        llm = OllamaLLMService(settings)
    else:
        llm = DisabledLLMService()

    async with aiosqlite.connect(str(settings.database_path)) as db:
        db.row_factory = aiosqlite.Row
        rag = RagService(db=db, llm=llm, run_id=run_id, top_k=top_k)
        answer = await rag.ask(question)

    console.print(f"\n[bold cyan]Question:[/bold cyan] {question}")
    console.print(f"\n[bold green]Answer:[/bold green] {answer.answer}")
    console.print(f"\n[dim]Sufficient evidence: {answer.sufficient_evidence}[/dim]")

    if answer.citations:
        console.print("\n[bold]Sources:[/bold]")
        for cite in answer.citations:
            console.print(f"  • {cite.url} (crawled: {cite.crawled_at})")
