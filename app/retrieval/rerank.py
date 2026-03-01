import re

from app.models import RetrievedChunk


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(t) > 1}


def rerank(query: str, chunks: list[RetrievedChunk], top_n: int = 8) -> list[RetrievedChunk]:
    """
    Lightweight reranker combining RRF score and query-token overlap.
    """
    if top_n <= 0:
        return []
    if not chunks:
        return []

    query_tokens = _tokenize(query)

    def score(chunk: RetrievedChunk) -> float:
        text_tokens = _tokenize(chunk.text)
        heading_tokens = _tokenize(" ".join([chunk.h1 or "", chunk.h2 or "", chunk.h3 or ""]))
        overlap = 0.0
        heading_overlap = 0.0
        if query_tokens:
            overlap = len(query_tokens & text_tokens) / len(query_tokens)
            heading_overlap = len(query_tokens & heading_tokens) / len(query_tokens)
        return chunk.score + 0.35 * overlap + 0.15 * heading_overlap

    return sorted(chunks, key=score, reverse=True)[:top_n]
