from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config import get_openai_api_key_value, get_pgvector_dsn_value, get_settings
from app.eval.runner import load_questions, run_evaluation
from app.logging_utils import setup_logging

app = typer.Typer(help="Doc Agent CLI")
console = Console()


def _count_md_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob("*.md"))


def _resolve_docs_dir(preferred: Path) -> Path:
    if preferred.exists():
        return preferred
    fallback = Path("doc")
    if fallback.exists():
        return fallback
    return preferred


@app.callback()
def _configure_app() -> None:
    setup_logging(get_settings())


@app.command()
def init() -> None:
    """Initialize local directories for docs."""
    settings = get_settings()
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    console.print("[green]Initialized directories:[/green]")
    console.print(f"- docs: {settings.docs_dir}")
    console.print(f"- pgvector table: {settings.pgvector_table}")
    console.print("Tip: copy .env.example to .env and set OPENAI_API_KEY")


@app.command()
def config() -> None:
    """Show current runtime configuration."""
    settings = get_settings()
    table = Table(title="Doc Agent Config")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    api_key_set = "yes" if get_openai_api_key_value() else "no"
    web_admin_token_set = (
        "yes"
        if settings.web_admin_token
        and settings.web_admin_token.get_secret_value().strip()
        else "no"
    )
    table.add_row("OPENAI_API_KEY", api_key_set)
    table.add_row("OPENAI_CHAT_MODEL", settings.openai_chat_model)
    table.add_row("OPENAI_EMBEDDING_MODEL", settings.openai_embedding_model)
    table.add_row("DOCS_DIR", str(settings.docs_dir))
    table.add_row("PGVECTOR_DSN", "yes" if get_pgvector_dsn_value() else "no")
    table.add_row("PGVECTOR_TABLE", settings.pgvector_table)
    table.add_row("PGVECTOR_DIM", str(settings.pgvector_dim))
    table.add_row("CHUNK_SIZE", str(settings.chunk_size))
    table.add_row("CHUNK_OVERLAP", str(settings.chunk_overlap))
    table.add_row("RETRIEVAL_TOP_K", str(settings.retrieval_top_k))
    table.add_row("RERANK_TOP_N", str(settings.rerank_top_n))
    table.add_row("QUERY_VARIANTS", str(settings.query_variants))
    table.add_row("RETRY_MAX_ATTEMPTS", str(settings.retry_max_attempts))
    table.add_row("RETRY_BASE_SECONDS", str(settings.retry_base_seconds))
    table.add_row("LOG_LEVEL", settings.log_level)
    table.add_row("LOG_FILE", str(settings.log_file))
    table.add_row("WEB_HOST", settings.web_host)
    table.add_row("WEB_PORT", str(settings.web_port))
    table.add_row("WEB_SESSION_WINDOW", str(settings.web_session_window))
    table.add_row("WEB_ADMIN_TOKEN", web_admin_token_set)
    console.print(table)


@app.command()
def ingest(
    docs_dir: Optional[Path] = typer.Option(
        None, help="Directory containing markdown documentation."
    ),
    reset: bool = typer.Option(False, help="Delete and rebuild the whole collection."),
    incremental: bool = typer.Option(
        True,
        "--incremental/--full",
        help="Incremental mode updates only changed docs; --full rewrites all docs.",
    ),
) -> None:
    """Build or rebuild vector index from markdown docs."""
    from app.ingest.indexer import build_index

    settings = get_settings()
    target_dir = _resolve_docs_dir(docs_dir or settings.docs_dir)
    if not get_openai_api_key_value():
        console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(code=1)

    if not target_dir.exists():
        console.print(f"[red]Docs directory not found: {target_dir}[/red]")
        raise typer.Exit(code=1)

    postgres_dsn = get_pgvector_dsn_value()
    if not postgres_dsn:
        console.print("[red]PGVECTOR_DSN (or DATABASE_URL) is not set.[/red]")
        raise typer.Exit(code=1)

    stats = build_index(
        docs_dir=target_dir,
        embedding_model=settings.openai_embedding_model,
        api_key=get_openai_api_key_value(),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        postgres_dsn=postgres_dsn,
        postgres_table=settings.pgvector_table,
        postgres_dim=settings.pgvector_dim,
        reset=reset,
        incremental=incremental,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
    )
    console.print("[green]Index build complete.[/green]")
    console.print(f"- mode: {stats.mode}")
    console.print(f"- docs indexed: {stats.docs_count}")
    console.print(f"- chunks written: {stats.chunks_count}")
    if stats.mode == "incremental":
        console.print(f"- changed docs: {stats.changed_docs}")
        console.print(f"- removed docs: {stats.removed_docs}")
        console.print(f"- unchanged docs: {stats.unchanged_docs}")
    console.print(f"- collection: {stats.collection_name}")


@app.command()
def ask(
    q: str = typer.Option(..., "--q", help="Question to ask the agent."),
    platform: str = typer.Option("", "--platform", help="Metadata filter: platform, e.g. android."),
    product: str = typer.Option("", "--product", help="Metadata filter: product, e.g. video-calling."),
) -> None:
    """Run single-turn QA with citations."""
    from app.qa.chain import answer as run_answer

    try:
        result = run_answer(
            q,
            platform=platform.strip() or None,
            product=product.strip() or None,
        )
    except Exception as exc:
        console.print(f"[red]ask failed:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(Panel.fit(result.answer_text, title="Answer"))
    console.print(f"Latency: {result.latency_ms} ms")
    if result.citations:
        table = Table(title="Sources")
        table.add_column("Chunk ID", style="cyan")
        table.add_column("Source", style="white")
        table.add_column("Heading", style="green")
        for citation in result.citations:
            table.add_row(citation.chunk_id, citation.source_path, citation.heading)
        console.print(table)
    else:
        console.print("Sources: (none)")


@app.command()
def chat(
    platform: str = typer.Option("", "--platform", help="Metadata filter: platform."),
    product: str = typer.Option("", "--product", help="Metadata filter: product."),
) -> None:
    """Interactive REPL shell for multi-turn chat."""
    from app.qa.chain import answer as run_answer

    console.print("Entering chat mode. Type 'exit' to quit.")
    while True:
        user_input = typer.prompt("you")
        if user_input.strip().lower() in {"exit", "quit"}:
            console.print("Bye.")
            break
        try:
            result = run_answer(
                user_input,
                platform=platform.strip() or None,
                product=product.strip() or None,
            )
            console.print(Panel.fit(result.answer_text, title="assistant"))
            if result.citations:
                source_labels = [f"{c.source_path}#{c.chunk_id}" for c in result.citations]
                console.print("sources: " + "; ".join(source_labels))
        except Exception as exc:
            console.print(f"[red]chat failed:[/red] {exc}")


@app.command()
def eval(
    dataset: Path = typer.Option(..., "--dataset", help="Path to evaluation dataset file."),
    max_questions: int = typer.Option(0, "--max-questions", help="Limit evaluated questions (0 = all)."),
    min_citation_presence: float = typer.Option(
        1.0, "--min-citation-presence", help="Minimum citation presence rate [0,1]."
    ),
    max_avg_latency_ms: float = typer.Option(
        8000.0, "--max-avg-latency-ms", help="Maximum average latency in milliseconds."
    ),
    max_insufficient_rate: float = typer.Option(
        0.4, "--max-insufficient-rate", help="Maximum insufficient evidence rate [0,1]."
    ),
    platform: str = typer.Option("", "--platform", help="Metadata filter: platform."),
    product: str = typer.Option("", "--product", help="Metadata filter: product."),
) -> None:
    """Run batch evaluation against a JSONL dataset."""
    from app.qa.chain import answer as run_answer

    try:
        questions = load_questions(dataset)
    except Exception as exc:
        console.print(f"[red]Failed to load dataset:[/red] {exc}")
        raise typer.Exit(code=1)

    if max_questions > 0:
        questions = questions[:max_questions]
    if not questions:
        console.print("[red]No valid questions in dataset.[/red]")
        raise typer.Exit(code=1)

    answer_fn = lambda question: run_answer(
        question,
        platform=platform.strip() or None,
        product=product.strip() or None,
    )
    summary_obj = run_evaluation(questions=questions, answer_fn=answer_fn)

    summary = Table(title="Evaluation Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Total Questions", str(summary_obj.total))
    summary.add_row("Answered", str(summary_obj.answered))
    summary.add_row("Insufficient Evidence", str(summary_obj.insufficient))
    summary.add_row("With Citations", str(summary_obj.with_citations))
    summary.add_row("Errors", str(summary_obj.errors))
    summary.add_row("Citation Presence", f"{summary_obj.citation_presence * 100:.1f}%")
    summary.add_row("Insufficient Rate", f"{summary_obj.insufficient_rate * 100:.1f}%")
    summary.add_row("Average Latency", f"{summary_obj.avg_latency_ms:.1f} ms")
    console.print(summary)

    passed = summary_obj.passes(
        min_citation_presence=min_citation_presence,
        max_avg_latency_ms=max_avg_latency_ms,
        max_insufficient_rate=max_insufficient_rate,
    )
    if passed:
        console.print("[green]Acceptance: PASS[/green]")
    else:
        console.print("[red]Acceptance: FAIL[/red]")
        console.print(
            "Thresholds -> "
            f"citation>={min_citation_presence:.2f}, "
            f"avg_latency<={max_avg_latency_ms:.1f}ms, "
            f"insufficient<={max_insufficient_rate:.2f}"
        )
        raise typer.Exit(code=2)


@app.command()
def stats() -> None:
    """Show basic local repository stats for docs/pgvector assets."""
    settings = get_settings()
    resolved_docs_dir = _resolve_docs_dir(settings.docs_dir)
    md_count = _count_md_files(resolved_docs_dir)
    console.print(f"Docs directory: {resolved_docs_dir} (md files: {md_count})")
    dsn = get_pgvector_dsn_value()
    if not dsn:
        console.print("[yellow]PGVECTOR_DSN is not configured.[/yellow]")
        return
    try:
        from app.vector.postgres_store import vector_count as pg_vector_count

        count = pg_vector_count(dsn=dsn, table=settings.pgvector_table)
        console.print("Vector backend: postgres")
        console.print(f"Table: {settings.pgvector_table}")
        console.print(f"Vector count: {count}")
    except Exception as exc:
        console.print(f"[red]Failed to query pgvector stats:[/red] {exc}")


if __name__ == "__main__":
    app()
