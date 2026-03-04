import logging
from pathlib import Path

from app.models import IndexStats
from app.vector.postgres_store import (
    chunk_rows_from_documents,
    delete_by_doc_ids as pg_delete_by_doc_ids,
    ensure_vector_table,
    load_existing_doc_hashes as pg_load_existing_doc_hashes,
    reset_table as pg_reset_table,
    upsert_chunk_rows as pg_upsert_chunk_rows,
)

logger = logging.getLogger(__name__)


def _import_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings


def _load_docs_and_chunks(
    docs_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
):
    from app.ingest.chunker import ChunkConfig, split_documents
    from app.ingest.loader import load_markdown_documents

    docs = load_markdown_documents(docs_dir)
    chunks = split_documents(
        docs,
        ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap),
    )
    return docs, chunks


def _compute_doc_delta(
    existing_doc_hashes: dict[str, str],
    new_doc_hashes: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    changed_docs = [
        doc_id
        for doc_id, doc_hash in new_doc_hashes.items()
        if existing_doc_hashes.get(doc_id) != doc_hash
    ]
    removed_docs = [doc_id for doc_id in existing_doc_hashes if doc_id not in new_doc_hashes]
    unchanged_docs = [
        doc_id
        for doc_id, doc_hash in new_doc_hashes.items()
        if existing_doc_hashes.get(doc_id) == doc_hash
    ]
    return sorted(changed_docs), sorted(removed_docs), sorted(unchanged_docs)


def build_index(
    docs_dir: Path,
    embedding_model: str,
    api_key: str | None,
    chunk_size: int,
    chunk_overlap: int,
    postgres_dsn: str,
    postgres_table: str = "docagent_chunks",
    postgres_dim: int = 3072,
    reset: bool = False,
    incremental: bool = True,
    retry_max_attempts: int = 3,
    retry_base_seconds: float = 0.8,
) -> IndexStats:
    """Build vector index from markdown docs and persist to PostgreSQL/pgvector."""
    from app.utils.retry import run_with_retry

    docs, chunks = _load_docs_and_chunks(
        docs_dir=docs_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    new_doc_hashes = {str(doc.metadata["doc_id"]): str(doc.metadata.get("doc_hash", "")) for doc in docs}
    chunks_by_doc_id: dict[str, list] = {}
    for chunk in chunks:
        doc_id = str(chunk.metadata.get("doc_id", ""))
        chunks_by_doc_id.setdefault(doc_id, []).append(chunk)

    OpenAIEmbeddings = _import_embeddings()
    ensure_vector_table(
        dsn=postgres_dsn,
        table=postgres_table,
        vector_dim=postgres_dim,
    )

    changed_docs: list[str] = []
    removed_docs: list[str] = []
    unchanged_docs: list[str] = []
    chunks_to_write = chunks
    mode = "reset" if reset else "full"

    if reset:
        pg_reset_table(dsn=postgres_dsn, table=postgres_table)
    elif incremental:
        mode = "incremental"
        existing_doc_hashes = pg_load_existing_doc_hashes(
            dsn=postgres_dsn,
            table=postgres_table,
        )
        changed_docs, removed_docs, unchanged_docs = _compute_doc_delta(
            existing_doc_hashes=existing_doc_hashes,
            new_doc_hashes=new_doc_hashes,
        )
        chunks_to_write = []
        for doc_id in changed_docs:
            chunks_to_write.extend(chunks_by_doc_id.get(doc_id, []))

        if removed_docs:
            pg_delete_by_doc_ids(dsn=postgres_dsn, table=postgres_table, doc_ids=removed_docs)
            logger.info("Removed %d deleted docs from pgvector store.", len(removed_docs))
        if changed_docs:
            pg_delete_by_doc_ids(dsn=postgres_dsn, table=postgres_table, doc_ids=changed_docs)
            logger.info("Reindexing %d changed docs in pgvector store.", len(changed_docs))
        if not changed_docs and not removed_docs:
            logger.info("No document changes detected. Skipping index write.")

    if chunks_to_write:
        embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key)
        vectors = embeddings.embed_documents([chunk.page_content for chunk in chunks_to_write])
        rows = chunk_rows_from_documents(chunks=chunks_to_write, embeddings=vectors)

        def _write_rows() -> None:
            pg_upsert_chunk_rows(
                dsn=postgres_dsn,
                table=postgres_table,
                rows=rows,
            )

        run_with_retry(
            fn=_write_rows,
            max_attempts=retry_max_attempts,
            base_delay_seconds=retry_base_seconds,
            operation_name="pgvector_upsert_rows",
        )

    return IndexStats(
        docs_count=len(docs),
        chunks_count=len(chunks_to_write),
        collection_name=postgres_table,
        mode=mode,
        changed_docs=len(changed_docs),
        removed_docs=len(removed_docs),
        unchanged_docs=len(unchanged_docs),
    )
