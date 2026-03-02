from app.models import Citation, RetrievedChunk


def heading_from_chunk(chunk: RetrievedChunk) -> str:
    parts = [part for part in [chunk.h1, chunk.h2, chunk.h3] if part]
    return " > ".join(parts) if parts else "Unknown heading"


def citations_from_chunk_ids(
    chunk_ids: list[str], retrieved_chunks: list[RetrievedChunk]
) -> list[Citation]:
    by_id = {chunk.chunk_id: chunk for chunk in retrieved_chunks}
    citations: list[Citation] = []
    for chunk_id in chunk_ids:
        chunk = by_id.get(chunk_id)
        if not chunk:
            continue
        citations.append(
            Citation(
                source_path=chunk.source_path,
                heading=heading_from_chunk(chunk),
                chunk_id=chunk.chunk_id,
                source_url=chunk.source_url,
            )
        )
    return citations
