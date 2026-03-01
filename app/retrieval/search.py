import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.models import RetrievedChunk
from app.utils.retry import run_with_retry

logger = logging.getLogger(__name__)


@dataclass
class _FusionItem:
    chunk: RetrievedChunk
    rrf_score: float = 0.0
    best_similarity: float = 0.0


def _normalize_chunk_id(source_path: str, text: str) -> str:
    seed = f"{source_path}:{text[:120]}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def build_metadata_filter(platform: Optional[str], product: Optional[str]) -> dict | None:
    clauses: list[dict] = []
    if platform and platform.strip():
        clauses.append({"platform": {"$eq": platform.strip()}})
    if product and product.strip():
        clauses.append({"product": {"$eq": product.strip()}})
    if not clauses:
        return None
    return {"$and": clauses}


def retrieve(
    queries: list[str],
    top_k: int,
    persist_dir: Path,
    collection_name: str,
    embedding_model: str,
    api_key: str | None,
    platform: str | None = None,
    product: str | None = None,
    retry_max_attempts: int = 3,
    retry_base_seconds: float = 0.8,
) -> list[RetrievedChunk]:
    """
    Run multi-query vector retrieval and fuse results with Reciprocal Rank Fusion (RRF).
    """
    if not queries or top_k <= 0:
        return []

    if not persist_dir.exists():
        return []

    embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key)
    vector_store = Chroma(
        collection_name=collection_name,
        persist_directory=str(persist_dir),
        embedding_function=embeddings,
    )
    metadata_filter = build_metadata_filter(platform=platform, product=product)

    fused: dict[str, _FusionItem] = {}
    rrf_k = 60.0

    for query in queries:
        def _search():
            return vector_store.similarity_search_with_score(
                query, k=top_k, filter=metadata_filter
            )

        try:
            results = run_with_retry(
                fn=_search,
                max_attempts=retry_max_attempts,
                base_delay_seconds=retry_base_seconds,
                operation_name="chroma_similarity_search",
            )
        except Exception as exc:
            logger.warning("Failed search variant '%s': %s", query, exc)
            continue
        for rank, (doc, raw_score) in enumerate(results, start=1):
            chunk_id = str(doc.metadata.get("chunk_id", "")).strip()
            source_path = str(doc.metadata.get("source_path", ""))
            if not chunk_id:
                chunk_id = _normalize_chunk_id(source_path, doc.page_content)

            if chunk_id not in fused:
                fused[chunk_id] = _FusionItem(
                    chunk=RetrievedChunk(
                        chunk_id=chunk_id,
                        text=doc.page_content,
                        score=0.0,
                        source_path=source_path,
                        h1=str(doc.metadata.get("h1", "")),
                        h2=str(doc.metadata.get("h2", "")),
                        h3=str(doc.metadata.get("h3", "")),
                    )
                )

            item = fused[chunk_id]
            item.rrf_score += 1.0 / (rrf_k + rank)
            item.best_similarity = max(item.best_similarity, -float(raw_score))

    ranked = sorted(
        fused.values(),
        key=lambda item: (item.rrf_score, item.best_similarity),
        reverse=True,
    )

    merged: list[RetrievedChunk] = []
    for item in ranked:
        chunk = item.chunk
        chunk.score = item.rrf_score
        merged.append(chunk)
    logger.info(
        "retrieve done: variants=%d top_k=%d results=%d filter=%s",
        len(queries),
        top_k,
        len(merged),
        metadata_filter or {},
    )
    return merged
