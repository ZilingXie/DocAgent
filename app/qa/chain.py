import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from app.config import get_openai_api_key_value, get_settings
from app.models import QAResult, RetrievedChunk
from app.qa.prompt import SYSTEM_PROMPT, build_answer_prompt
from app.retrieval.multi_query import generate_query_variants
from app.retrieval.rerank import rerank
from app.retrieval.search import retrieve
from app.utils.citation import citations_from_chunk_ids
from app.utils.retry import run_with_retry

logger = logging.getLogger(__name__)
_UNAVAILABLE_MODELS: set[str] = set()


def _format_context_chunks(chunks: list[RetrievedChunk]) -> str:
    blocks: list[str] = []
    for chunk in chunks:
        heading = " > ".join([item for item in [chunk.h1, chunk.h2, chunk.h3] if item]) or "Unknown heading"
        blocks.append(
            f"[{chunk.chunk_id}] {chunk.source_path} | {heading}\n"
            f"{chunk.text.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    content = text.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        if content.endswith("```"):
            content = content[:-3].strip()

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    payload = content[start : end + 1]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_valid_response(payload: dict[str, Any], allowed_chunk_ids: set[str]) -> bool:
    if not isinstance(payload.get("answer"), str):
        return False
    if not isinstance(payload.get("key_steps"), list):
        return False
    if not isinstance(payload.get("citations"), list):
        return False
    if not isinstance(payload.get("insufficient_evidence"), bool):
        return False
    for cid in payload["citations"]:
        if not isinstance(cid, str) or cid not in allowed_chunk_ids:
            return False
    if not payload["insufficient_evidence"] and len(payload["citations"]) == 0:
        return False
    return True


def _fallback_no_evidence(latency_ms: int) -> QAResult:
    return QAResult(
        answer_text="Not enough evidence in provided docs.",
        citations=[],
        used_chunks=[],
        latency_ms=latency_ms,
    )


def _build_answer_text(answer: str, key_steps: list[str]) -> str:
    cleaned_steps = [step.strip() for step in key_steps if isinstance(step, str) and step.strip()]
    if not cleaned_steps:
        return answer.strip()
    lines = [answer.strip(), "", "Key Steps:"]
    for idx, step in enumerate(cleaned_steps, start=1):
        lines.append(f"{idx}. {step}")
    return "\n".join(lines).strip()


def _invoke_llm_answer(
    query: str,
    context_chunks: list[RetrievedChunk],
    model_name: str,
    api_key: str | None,
    retry_max_attempts: int,
    retry_base_seconds: float,
    strict_retry: bool = False,
) -> dict[str, Any] | None:
    context_block = _format_context_chunks(context_chunks)
    prompt = build_answer_prompt(query, context_block)
    if strict_retry:
        prompt += (
            "\n\nRetry requirement:\n"
            "- Return JSON only.\n"
            "- Every citation must be one of the provided chunk ids.\n"
            "- If unsure, use insufficient evidence response."
        )

    model_candidates: list[str] = []
    for candidate in [model_name, "gpt-4.1", "gpt-4o-mini"]:
        if candidate in _UNAVAILABLE_MODELS:
            continue
        if candidate not in model_candidates:
            model_candidates.append(candidate)

    last_exception: Exception | None = None
    for candidate_model in model_candidates:
        try:
            llm = ChatOpenAI(model=candidate_model, temperature=0, api_key=api_key)
            response = run_with_retry(
                fn=lambda: llm.invoke(
                    [
                        ("system", SYSTEM_PROMPT),
                        ("user", prompt),
                    ]
                ),
                max_attempts=retry_max_attempts,
                base_delay_seconds=retry_base_seconds,
                operation_name=f"llm_answer_{candidate_model}",
            )
            content = response.content if isinstance(response.content, str) else str(response.content)
            return _extract_json_payload(content)
        except Exception as exc:
            last_exception = exc
            text = str(exc).lower()
            if "model_not_found" in text or "does not exist" in text:
                _UNAVAILABLE_MODELS.add(candidate_model)
                continue
            raise

    if last_exception:
        raise last_exception
    return None


def answer(query: str, platform: str | None = None, product: str | None = None) -> QAResult:
    """
    End-to-end RAG chain:
    multi-query rewrite -> vector retrieval + RRF -> rerank -> grounded answer with citations.
    """
    started = time.perf_counter()
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    variants = generate_query_variants(query=query, n=settings.query_variants)
    api_key = get_openai_api_key_value()
    retrieved = retrieve(
        queries=variants,
        top_k=settings.retrieval_top_k,
        persist_dir=Path(settings.chroma_persist_dir),
        collection_name=settings.chroma_collection,
        embedding_model=settings.openai_embedding_model,
        api_key=api_key,
        platform=platform,
        product=product,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
    )
    top_chunks = rerank(query=query, chunks=retrieved, top_n=settings.rerank_top_n)
    if not top_chunks:
        latency = int((time.perf_counter() - started) * 1000)
        logger.info("qa insufficient: no retrieved chunks, latency_ms=%d", latency)
        return _fallback_no_evidence(latency)

    allowed_chunk_ids = {chunk.chunk_id for chunk in top_chunks}
    payload = _invoke_llm_answer(
        query=query,
        context_chunks=top_chunks,
        model_name=settings.openai_chat_model,
        api_key=api_key,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        strict_retry=False,
    )
    if payload is None or not _is_valid_response(payload, allowed_chunk_ids):
        payload = _invoke_llm_answer(
            query=query,
            context_chunks=top_chunks,
            model_name=settings.openai_chat_model,
            api_key=api_key,
            retry_max_attempts=settings.retry_max_attempts,
            retry_base_seconds=settings.retry_base_seconds,
            strict_retry=True,
        )

    latency = int((time.perf_counter() - started) * 1000)
    if payload is None or not _is_valid_response(payload, allowed_chunk_ids):
        logger.warning("qa invalid payload; returning insufficient evidence.")
        return _fallback_no_evidence(latency)

    if payload["insufficient_evidence"] is True:
        logger.info("qa insufficient evidence from model.")
        return _fallback_no_evidence(latency)

    citations = citations_from_chunk_ids(payload["citations"], top_chunks)
    if not citations:
        logger.warning("qa produced empty citations after validation.")
        return _fallback_no_evidence(latency)

    answer_text = _build_answer_text(payload["answer"], payload.get("key_steps", []))
    logger.info(
        "qa answered: latency_ms=%d chunks=%d platform=%s product=%s",
        latency,
        len(top_chunks),
        platform or "",
        product or "",
    )
    return QAResult(
        answer_text=answer_text,
        citations=citations,
        used_chunks=top_chunks,
        latency_ms=latency,
    )
