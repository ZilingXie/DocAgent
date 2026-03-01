from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.ingest.chunker import ChunkConfig, split_documents
from app.ingest.loader import load_markdown_documents
from app.models import IndexStats
from app.utils.retry import run_with_retry

import logging

logger = logging.getLogger(__name__)


def _reset_collection(persist_dir: Path, collection_name: str) -> None:
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(collection_name)
    except Exception:
        # Collection might not exist, which is fine for reset flow.
        pass


def _load_existing_doc_hashes(collection, batch_size: int = 2000) -> dict[str, str]:
    mapping: dict[str, str] = {}
    offset = 0
    while True:
        data = collection.get(include=["metadatas"], limit=batch_size, offset=offset)
        metadatas = data.get("metadatas") or []
        if not metadatas:
            break
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            doc_id = str(metadata.get("doc_id", "")).strip()
            doc_hash = str(metadata.get("doc_hash", "")).strip()
            if doc_id and doc_hash and doc_id not in mapping:
                mapping[doc_id] = doc_hash
        if len(metadatas) < batch_size:
            break
        offset += len(metadatas)
    return mapping


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
    unchanged_docs = [doc_id for doc_id, doc_hash in new_doc_hashes.items() if existing_doc_hashes.get(doc_id) == doc_hash]
    return sorted(changed_docs), sorted(removed_docs), sorted(unchanged_docs)


def _chunk_ids(chunks) -> list[str]:
    return [str(chunk.metadata.get("chunk_id", "")) for chunk in chunks]


def build_index(
    docs_dir: Path,
    collection_name: str,
    persist_dir: Path,
    embedding_model: str,
    api_key: str | None,
    chunk_size: int,
    chunk_overlap: int,
    reset: bool = False,
    incremental: bool = True,
    retry_max_attempts: int = 3,
    retry_base_seconds: float = 0.8,
) -> IndexStats:
    """Build vector index from markdown docs and persist to Chroma."""
    docs = load_markdown_documents(docs_dir)
    chunks = split_documents(docs, ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap))
    new_doc_hashes = {
        str(doc.metadata["doc_id"]): str(doc.metadata.get("doc_hash", ""))
        for doc in docs
    }
    chunks_by_doc_id: dict[str, list] = {}
    for chunk in chunks:
        doc_id = str(chunk.metadata.get("doc_id", ""))
        chunks_by_doc_id.setdefault(doc_id, []).append(chunk)

    persist_dir.mkdir(parents=True, exist_ok=True)
    if reset:
        _reset_collection(persist_dir, collection_name)

    embedding = OpenAIEmbeddings(model=embedding_model, api_key=api_key)
    vector_store = Chroma(
        collection_name=collection_name,
        persist_directory=str(persist_dir),
        embedding_function=embedding,
    )

    changed_docs: list[str] = []
    removed_docs: list[str] = []
    unchanged_docs: list[str] = []
    chunks_to_write = chunks
    mode = "reset" if reset else "full"

    if not reset and incremental:
        mode = "incremental"
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_or_create_collection(collection_name)
        existing_doc_hashes = _load_existing_doc_hashes(collection)
        changed_docs, removed_docs, unchanged_docs = _compute_doc_delta(
            existing_doc_hashes=existing_doc_hashes,
            new_doc_hashes=new_doc_hashes,
        )
        chunks_to_write = []
        for doc_id in changed_docs:
            chunks_to_write.extend(chunks_by_doc_id.get(doc_id, []))

        if removed_docs:
            vector_store.delete(where={"doc_id": {"$in": removed_docs}})
            logger.info("Removed %d deleted docs from index.", len(removed_docs))
        if changed_docs:
            vector_store.delete(where={"doc_id": {"$in": changed_docs}})
            logger.info("Reindexing %d changed docs.", len(changed_docs))
        if not changed_docs and not removed_docs:
            logger.info("No document changes detected. Skipping index write.")

    if chunks_to_write:
        ids = _chunk_ids(chunks_to_write)

        def _write_chunks() -> None:
            vector_store.add_documents(chunks_to_write, ids=ids)

        run_with_retry(
            fn=_write_chunks,
            max_attempts=retry_max_attempts,
            base_delay_seconds=retry_base_seconds,
            operation_name="chroma_add_documents",
        )

    return IndexStats(
        docs_count=len(docs),
        chunks_count=len(chunks_to_write),
        collection_name=collection_name,
        mode=mode,
        changed_docs=len(changed_docs),
        removed_docs=len(removed_docs),
        unchanged_docs=len(unchanged_docs),
    )
