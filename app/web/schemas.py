from typing import Literal

from pydantic import BaseModel, Field


class CitationOut(BaseModel):
    source_path: str
    heading: str
    chunk_id: str
    source_link: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    platform: str | None = None
    product: str | None = None


class AskResponse(BaseModel):
    answer_text: str
    citations: list[CitationOut]
    latency_ms: int


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    platform: str | None = None
    product: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer_text: str
    citations: list[CitationOut]
    latency_ms: int
    history: list[ChatTurn]


class ChatResetRequest(BaseModel):
    session_id: str = Field(..., min_length=6, max_length=100)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    api_key_set: bool
    chroma_collection: str
    chroma_persist_dir: str
    chroma_exists: bool


class AdminIngestRequest(BaseModel):
    docs_dir: str | None = None
    reset: bool = False
    incremental: bool = True


class AdminIngestResponse(BaseModel):
    docs_count: int
    chunks_count: int
    collection_name: str
    mode: str
    changed_docs: int
    removed_docs: int
    unchanged_docs: int
