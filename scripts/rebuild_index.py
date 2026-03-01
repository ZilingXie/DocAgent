import argparse
from pathlib import Path

from app.config import get_openai_api_key_value, get_settings
from app.ingest.indexer import build_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild or incrementally update vector index.")
    parser.add_argument("--reset", action="store_true", help="Delete and rebuild the whole collection.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Re-index all docs without reset (disables incremental delta).",
    )
    args = parser.parse_args()

    settings = get_settings()
    docs_dir = Path(settings.docs_dir)
    if not docs_dir.exists() and Path("doc").exists():
        docs_dir = Path("doc")
    stats = build_index(
        docs_dir=docs_dir,
        collection_name=settings.chroma_collection,
        persist_dir=Path(settings.chroma_persist_dir),
        embedding_model=settings.openai_embedding_model,
        api_key=get_openai_api_key_value(),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        reset=args.reset,
        incremental=not args.full,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
    )
    print(
        f"mode={stats.mode} docs={stats.docs_count} chunks={stats.chunks_count} "
        f"changed_docs={stats.changed_docs} removed_docs={stats.removed_docs} "
        f"unchanged_docs={stats.unchanged_docs} collection={stats.collection_name}"
    )


if __name__ == "__main__":
    main()
