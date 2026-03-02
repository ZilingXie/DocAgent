import logging
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_openai_api_key_value, get_settings
from app.ingest.indexer import build_index
from app.logging_utils import setup_logging
from app.qa.chain import answer as run_answer
from app.web.schemas import (
    AdminIngestRequest,
    AdminIngestResponse,
    AskRequest,
    AskResponse,
    ChatRequest,
    ChatResetRequest,
    ChatResponse,
    CitationOut,
    HealthResponse,
)
from app.web.session_store import InMemorySessionStore

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))


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
        chroma_dir = Path(current.chroma_persist_dir)
        chroma_exists = chroma_dir.exists()
        status = "ok" if api_key_set and chroma_exists else "degraded"
        return HealthResponse(
            status=status,
            api_key_set=api_key_set,
            chroma_collection=current.chroma_collection,
            chroma_persist_dir=str(chroma_dir),
            chroma_exists=chroma_exists,
        )

    @app.post("/api/ask", response_model=AskResponse)
    def ask(payload: AskRequest) -> AskResponse:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must not be empty.")

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

        session_store.append(session_id, "user", message)
        session_store.append(session_id, "assistant", result.answer_text)
        new_history = session_store.history(session_id)

        return ChatResponse(
            session_id=session_id,
            answer_text=result.answer_text,
            citations=_to_citations(result),
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

        try:
            stats = build_index(
                docs_dir=docs_dir,
                collection_name=settings.chroma_collection,
                persist_dir=Path(settings.chroma_persist_dir),
                embedding_model=settings.openai_embedding_model,
                api_key=get_openai_api_key_value(),
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
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
