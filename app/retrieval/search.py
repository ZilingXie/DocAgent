import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from app.models import RetrievedChunk
from app.vector.postgres_store import similarity_search_with_score as pg_similarity_search

logger = logging.getLogger(__name__)


def _import_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings


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
    embedding_model: str,
    api_key: str | None,
    postgres_dsn: str,
    postgres_table: str = "docagent_chunks",
    platform: str | None = None,
    product: str | None = None,
) -> list[RetrievedChunk]:
    """
    Run multi-query vector retrieval and fuse results with Reciprocal Rank Fusion (RRF).
    """
    if not queries or top_k <= 0:
        return []

    OpenAIEmbeddings = _import_embeddings()
    embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key)

    fused: dict[str, _FusionItem] = {}
    rrf_k = 60.0
    query_vectors = embeddings.embed_documents(queries)
    for query, vector in zip(queries, query_vectors):
        try:
            results = pg_similarity_search(
                dsn=postgres_dsn,
                table=postgres_table,
                query_embedding=vector,
                top_k=top_k,
                platform=platform,
                product=product,
            )
        except Exception as exc:
            logger.warning("Failed postgres search variant '%s': %s", query, exc)
            continue

        for rank, (chunk, similarity) in enumerate(results, start=1):
            if not chunk.chunk_id:
                chunk.chunk_id = _normalize_chunk_id(chunk.source_path, chunk.text)
            if chunk.chunk_id not in fused:
                fused[chunk.chunk_id] = _FusionItem(chunk=chunk)
            item = fused[chunk.chunk_id]
            item.rrf_score += 1.0 / (rrf_k + rank)
            item.best_similarity = max(item.best_similarity, float(similarity))

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
        "retrieve done (postgres): variants=%d top_k=%d results=%d platform=%s product=%s",
        len(queries),
        top_k,
        len(merged),
        platform or "",
        product or "",
    )
    return merged
