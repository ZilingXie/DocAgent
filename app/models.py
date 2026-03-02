from dataclasses import dataclass
from typing import Optional


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    source_path: str
    h1: Optional[str] = None
    h2: Optional[str] = None
    h3: Optional[str] = None
    source_url: Optional[str] = None


@dataclass
class Citation:
    source_path: str
    heading: str
    chunk_id: str
    source_url: Optional[str] = None


@dataclass
class QAResult:
    answer_text: str
    citations: list[Citation]
    used_chunks: list[RetrievedChunk]
    latency_ms: int


@dataclass
class IndexStats:
    docs_count: int
    chunks_count: int
    collection_name: str
    mode: str = "full"
    changed_docs: int = 0
    removed_docs: int = 0
    unchanged_docs: int = 0
