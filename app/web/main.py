import logging
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_openai_api_key_value, get_pgvector_dsn_value, get_settings
from app.ingest.indexer import build_index
from app.logging_utils import setup_logging
from app.qa.chain import answer as run_answer
from app.web.intent import (
    OUT_OF_SCOPE_REPLY,
    is_obviously_out_of_scope,
    should_replace_insufficient_reply,
)
from app.web.schemas import (
    AdminIngestRequest,
    AdminIngestResponse,
    AdminVectorizeTextRequest,
    AdminVectorizeTextResponse,
    AskRequest,
    AskResponse,
    ChatRequest,
    ChatResetRequest,
    ChatResponse,
    CitationOut,
    HealthResponse,
)
from app.web.session_store import InMemorySessionStore
from app.vector.postgres_store import (
    ensure_vector_table,
    ping_database,
    table_exists as pg_table_exists,
    upsert_text,
)

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


def _import_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _truncate_text(text: str, limit: int = 700) -> str:
    content = text.strip()
    if len(content) <= limit:
        return content
    return content[: limit - 3] + "..."


def _build_chat_query(message: str, history: list) -> str:
    if not history:
        return message
    lines = ["Conversation memory:"]
    for turn in history:
        lines.append(f"{turn.role}: {_truncate_text(turn.content)}")
    lines.append("")
    lines.append(f"Current user question: {message}")
    return "\n".join(lines)


def _to_citations(result) -> list[CitationOut]:
    def _source_link(item) -> str:
        source_url = (item.source_url or "").strip()
        if source_url:
            return source_url
        return f"/docs/{quote(item.source_path, safe='/')}"

    return [
        CitationOut(
            source_path=item.source_path,
            heading=item.heading,
            chunk_id=item.chunk_id,
            source_link=_source_link(item),
        )
        for item in result.citations
    ]


def _resolve_docs_dir(preferred: Path) -> Path:
    if preferred.exists():
        return preferred
    fallback = Path("doc")
    if fallback.exists():
        return fallback
    return preferred


def _require_admin_token(received_token: str | None) -> None:
    settings = get_settings()
    expected = (
        settings.web_admin_token.get_secret_value()
        if settings.web_admin_token is not None
        else ""
    )
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin ingest is disabled. Set WEB_ADMIN_TOKEN to enable it.",
        )
    if not received_token or received_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token.")


def _resolve_doc_file(doc_path: str) -> Path:
    settings = get_settings()
    candidate_roots: list[Path] = []
    primary = _resolve_docs_dir(Path(settings.docs_dir))
    candidate_roots.append(primary)
    fallback = Path("doc")
    if fallback not in candidate_roots:
        candidate_roots.append(fallback)

    for root in candidate_roots:
        root_resolved = root.resolve()
        candidate = (root_resolved / doc_path).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid documentation path.")
        if candidate.exists() and candidate.is_file():
            return candidate

    raise HTTPException(status_code=404, detail="Documentation file not found.")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    app = FastAPI(title="DocAgent Web", version="0.1.0")
    app.state.session_store = InMemorySessionStore(
        max_turn_pairs=max(20, settings.web_session_window)
    )
    app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"title": "DocAgent"},
        )

    @app.get("/docs/{doc_path:path}")
    def docs_file(doc_path: str) -> FileResponse:
        file_path = _resolve_doc_file(doc_path)
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        current = get_settings()
        api_key_set = bool(get_openai_api_key_value())
        dsn = get_pgvector_dsn_value()
        vector_store_ready = False
        if dsn:
            try:
                vector_store_ready = ping_database(dsn=dsn) and pg_table_exists(
                    dsn=dsn,
                    table=current.pgvector_table,
                )
            except Exception:
                vector_store_ready = False

        status = "ok" if api_key_set and vector_store_ready else "degraded"
        return HealthResponse(
            status=status,
            api_key_set=api_key_set,
            vector_store_ready=vector_store_ready,
            pgvector_table=current.pgvector_table,
        )

    @app.post("/api/ask", response_model=AskResponse)
    def ask(payload: AskRequest) -> AskResponse:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must not be empty.")
        if is_obviously_out_of_scope(question):
            return AskResponse(answer_text=OUT_OF_SCOPE_REPLY, citations=[], latency_ms=0)

        try:
            result = run_answer(
                question,
                platform=_clean_optional(payload.platform),
                product=_clean_optional(payload.product),
            )
        except Exception:
            logger.exception("ask endpoint failed")
            raise HTTPException(
                status_code=500, detail="Failed to answer request. Check server logs."
            )

        if should_replace_insufficient_reply(
            question=question, answer_text=result.answer_text, has_history=False
        ):
            return AskResponse(
                answer_text=OUT_OF_SCOPE_REPLY,
                citations=[],
                latency_ms=result.latency_ms,
            )

        return AskResponse(
            answer_text=result.answer_text,
            citations=_to_citations(result),
            latency_ms=result.latency_ms,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message must not be empty.")

        session_store: InMemorySessionStore = request.app.state.session_store
        session_id = session_store.get_or_create(payload.session_id)
        history = session_store.history(session_id)

        if is_obviously_out_of_scope(message):
            session_store.append(session_id, "user", message)
            session_store.append(session_id, "assistant", OUT_OF_SCOPE_REPLY)
            return ChatResponse(
                session_id=session_id,
                answer_text=OUT_OF_SCOPE_REPLY,
                citations=[],
                latency_ms=0,
                history=session_store.history(session_id),
            )

        query = _build_chat_query(message=message, history=history)

        try:
            result = run_answer(
                query,
                platform=_clean_optional(payload.platform),
                product=_clean_optional(payload.product),
            )
        except Exception:
            logger.exception("chat endpoint failed")
            raise HTTPException(
                status_code=500, detail="Failed to answer request. Check server logs."
            )

        answer_text = result.answer_text
        citations = _to_citations(result)
        if should_replace_insufficient_reply(
            question=message,
            answer_text=result.answer_text,
            has_history=bool(history),
        ):
            answer_text = OUT_OF_SCOPE_REPLY
            citations = []

        session_store.append(session_id, "user", message)
        session_store.append(session_id, "assistant", answer_text)
        new_history = session_store.history(session_id)

        return ChatResponse(
            session_id=session_id,
            answer_text=answer_text,
            citations=citations,
            latency_ms=result.latency_ms,
            history=new_history,
        )

    @app.post("/api/chat/reset")
    def chat_reset(payload: ChatResetRequest, request: Request) -> dict[str, str]:
        session_store: InMemorySessionStore = request.app.state.session_store
        session_store.reset(payload.session_id)
        return {"status": "ok", "session_id": payload.session_id}

    @app.post("/api/admin/ingest", response_model=AdminIngestResponse)
    def admin_ingest(
        payload: AdminIngestRequest,
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> AdminIngestResponse:
        _require_admin_token(x_admin_token)
        settings = get_settings()
        docs_dir = _resolve_docs_dir(
            Path(payload.docs_dir) if payload.docs_dir else Path(settings.docs_dir)
        )
        if not docs_dir.exists():
            raise HTTPException(
                status_code=400, detail=f"Docs directory not found: {docs_dir}"
            )
        dsn = get_pgvector_dsn_value()
        if not dsn:
            raise HTTPException(
                status_code=500,
                detail="PGVECTOR_DSN (or DATABASE_URL) is not configured.",
            )

        try:
            stats = build_index(
                docs_dir=docs_dir,
                embedding_model=settings.openai_embedding_model,
                api_key=get_openai_api_key_value(),
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                postgres_dsn=dsn,
                postgres_table=settings.pgvector_table,
                postgres_dim=settings.pgvector_dim,
                reset=payload.reset,
                incremental=payload.incremental,
                retry_max_attempts=settings.retry_max_attempts,
                retry_base_seconds=settings.retry_base_seconds,
            )
        except Exception:
            logger.exception("admin ingest failed")
            raise HTTPException(status_code=500, detail="Ingest failed. Check server logs.")

        return AdminIngestResponse(
            docs_count=stats.docs_count,
            chunks_count=stats.chunks_count,
            collection_name=stats.collection_name,
            mode=stats.mode,
            changed_docs=stats.changed_docs,
            removed_docs=stats.removed_docs,
            unchanged_docs=stats.unchanged_docs,
        )

    @app.post("/api/admin/vectorize", response_model=AdminVectorizeTextResponse)
    def admin_vectorize_text(
        payload: AdminVectorizeTextRequest,
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> AdminVectorizeTextResponse:
        _require_admin_token(x_admin_token)
        settings = get_settings()
        dsn = get_pgvector_dsn_value()
        if not dsn:
            raise HTTPException(
                status_code=500,
                detail="PGVECTOR_DSN (or DATABASE_URL) is not configured.",
            )

        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Text must not be empty.")

        try:
            api_key = get_openai_api_key_value()
            if not api_key:
                raise HTTPException(
                    status_code=503,
                    detail="OPENAI_API_KEY is not configured.",
                )
            ensure_vector_table(
                dsn=dsn,
                table=settings.pgvector_table,
                vector_dim=settings.pgvector_dim,
            )
            OpenAIEmbeddings = _import_embeddings()
            embeddings = OpenAIEmbeddings(
                model=settings.openai_embedding_model,
                api_key=api_key,
            )
            vector = embeddings.embed_query(text)
            chunk_id, latency_ms = upsert_text(
                dsn=dsn,
                table=settings.pgvector_table,
                vector_dim=settings.pgvector_dim,
                text=text,
                embedding=vector,
                chunk_id=_clean_optional(payload.chunk_id),
                doc_id=_clean_optional(payload.doc_id),
                doc_hash=_clean_optional(payload.doc_hash),
                source_path=_clean_optional(payload.source_path),
                source_url=_clean_optional(payload.source_url),
                platform=_clean_optional(payload.platform),
                product=_clean_optional(payload.product),
                h1=_clean_optional(payload.h1),
                h2=_clean_optional(payload.h2),
                h3=_clean_optional(payload.h3),
                metadata=payload.metadata or {},
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("admin vectorize failed")
            raise HTTPException(
                status_code=500,
                detail="Vectorize and store failed. Check server logs.",
            )

        return AdminVectorizeTextResponse(
            status="ok",
            chunk_id=chunk_id,
            latency_ms=latency_ms,
            table=settings.pgvector_table,
        )

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.web.main:app",
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
