import hashlib
import json
import logging
import time
from typing import Any

from app.models import RetrievedChunk

logger = logging.getLogger(__name__)


def _import_psycopg():
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - exercised only when dependency missing
        raise RuntimeError(
            "psycopg is required for PostgreSQL vector backend. "
            "Install dependency 'psycopg[binary]'."
        ) from exc
    return psycopg


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.10f}" for v in values) + "]"


def _hash_chunk_id(source_path: str, text: str) -> str:
    seed = f"{source_path}:{text[:160]}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def ensure_vector_table(
    *,
    dsn: str,
    table: str,
    vector_dim: int,
) -> None:
    if vector_dim <= 0:
        raise ValueError("PGVECTOR_DIM must be > 0")

    psycopg = _import_psycopg()
    sql = psycopg.sql
    idx_doc = f"{table}_doc_id_idx"
    idx_platform = f"{table}_platform_idx"
    idx_product = f"{table}_product_idx"
    idx_updated = f"{table}_updated_at_idx"

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {} (
                        id TEXT PRIMARY KEY,
                        doc_id TEXT NOT NULL,
                        doc_hash TEXT,
                        source_path TEXT NOT NULL,
                        h1 TEXT,
                        h2 TEXT,
                        h3 TEXT,
                        source_url TEXT,
                        platform TEXT,
                        product TEXT,
                        chunk_index INTEGER,
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding vector({}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(table), sql.SQL(str(int(vector_dim))))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (doc_id)").format(
                    sql.Identifier(idx_doc),
                    sql.Identifier(table),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (platform)").format(
                    sql.Identifier(idx_platform),
                    sql.Identifier(table),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (product)").format(
                    sql.Identifier(idx_product),
                    sql.Identifier(table),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (updated_at DESC)").format(
                    sql.Identifier(idx_updated),
                    sql.Identifier(table),
                )
            )
        conn.commit()


def ping_database(*, dsn: str) -> bool:
    psycopg = _import_psycopg()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            return bool(row and row[0] == 1)


def table_exists(*, dsn: str, table: str) -> bool:
    psycopg = _import_psycopg()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                )
                """,
                (table,),
            )
            row = cur.fetchone()
            return bool(row and row[0] is True)


def reset_table(*, dsn: str, table: str) -> None:
    psycopg = _import_psycopg()
    sql = psycopg.sql
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        conn.commit()


def load_existing_doc_hashes(*, dsn: str, table: str) -> dict[str, str]:
    psycopg = _import_psycopg()
    sql = psycopg.sql
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT DISTINCT ON (doc_id) doc_id, doc_hash
                    FROM {}
                    WHERE doc_id <> '' AND doc_hash IS NOT NULL AND doc_hash <> ''
                    ORDER BY doc_id, updated_at DESC
                    """
                ).format(sql.Identifier(table))
            )
            rows = cur.fetchall()
    return {str(doc_id): str(doc_hash) for doc_id, doc_hash in rows}


def delete_by_doc_ids(*, dsn: str, table: str, doc_ids: list[str]) -> int:
    if not doc_ids:
        return 0
    psycopg = _import_psycopg()
    sql = psycopg.sql
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {} WHERE doc_id = ANY(%s)").format(
                    sql.Identifier(table)
                ),
                (doc_ids,),
            )
            deleted = cur.rowcount or 0
        conn.commit()
    return int(deleted)


def vector_count(*, dsn: str, table: str) -> int:
    psycopg = _import_psycopg()
    sql = psycopg.sql
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
            row = cur.fetchone()
    return int(row[0] if row else 0)


def upsert_chunk_rows(
    *,
    dsn: str,
    table: str,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    psycopg = _import_psycopg()
    sql = psycopg.sql
    query = sql.SQL(
        """
        INSERT INTO {} (
            id,
            doc_id,
            doc_hash,
            source_path,
            h1,
            h2,
            h3,
            source_url,
            platform,
            product,
            chunk_index,
            content,
            metadata,
            embedding,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
            doc_id = EXCLUDED.doc_id,
            doc_hash = EXCLUDED.doc_hash,
            source_path = EXCLUDED.source_path,
            h1 = EXCLUDED.h1,
            h2 = EXCLUDED.h2,
            h3 = EXCLUDED.h3,
            source_url = EXCLUDED.source_url,
            platform = EXCLUDED.platform,
            product = EXCLUDED.product,
            chunk_index = EXCLUDED.chunk_index,
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding,
            updated_at = NOW()
        """
    ).format(sql.Identifier(table))

    payload = [
        (
            row["id"],
            row["doc_id"],
            row.get("doc_hash"),
            row["source_path"],
            row.get("h1"),
            row.get("h2"),
            row.get("h3"),
            row.get("source_url"),
            row.get("platform"),
            row.get("product"),
            row.get("chunk_index"),
            row["content"],
            json.dumps(row.get("metadata") or {}, ensure_ascii=False),
            _vector_literal(row["embedding"]),
        )
        for row in rows
    ]

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(query, payload)
        conn.commit()
    return len(rows)


def chunk_rows_from_documents(
    *,
    chunks: list,
    embeddings: list[list[float]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings):
        metadata = dict(chunk.metadata or {})
        source_path = str(metadata.get("source_path", "")).strip() or "doc/unknown.md"
        text = str(chunk.page_content or "")
        chunk_id = str(metadata.get("chunk_id", "")).strip() or _hash_chunk_id(source_path, text)
        doc_id = str(metadata.get("doc_id", "")).strip() or source_path
        chunk_index_raw = metadata.get("chunk_index")
        chunk_index = None
        try:
            if chunk_index_raw is not None and str(chunk_index_raw).strip() != "":
                chunk_index = int(chunk_index_raw)
        except Exception:
            chunk_index = None
        rows.append(
            {
                "id": chunk_id,
                "doc_id": doc_id,
                "doc_hash": str(metadata.get("doc_hash", "")).strip() or None,
                "source_path": source_path,
                "h1": str(metadata.get("h1", "")).strip() or None,
                "h2": str(metadata.get("h2", "")).strip() or None,
                "h3": str(metadata.get("h3", "")).strip() or None,
                "source_url": (
                    str(
                        metadata.get("source_url", "")
                        or metadata.get("exported_from", "")
                    ).strip()
                    or None
                ),
                "platform": str(metadata.get("platform", "")).strip() or None,
                "product": str(metadata.get("product", "")).strip() or None,
                "chunk_index": chunk_index,
                "content": text,
                "metadata": metadata,
                "embedding": embedding,
            }
        )
    return rows


def upsert_text(
    *,
    dsn: str,
    table: str,
    vector_dim: int,
    text: str,
    embedding: list[float],
    chunk_id: str | None = None,
    doc_id: str | None = None,
    doc_hash: str | None = None,
    source_path: str | None = None,
    source_url: str | None = None,
    platform: str | None = None,
    product: str | None = None,
    h1: str | None = None,
    h2: str | None = None,
    h3: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, int]:
    started = time.perf_counter()
    ensure_vector_table(dsn=dsn, table=table, vector_dim=vector_dim)
    normalized_text = text.strip()
    normalized_source_path = (source_path or "").strip() or "api/manual"
    normalized_chunk_id = (chunk_id or "").strip() or _hash_chunk_id(
        normalized_source_path, normalized_text
    )
    normalized_doc_id = (doc_id or "").strip() or normalized_source_path
    default_doc_hash = hashlib.sha1(normalized_text.encode("utf-8")).hexdigest()
    row = {
        "id": normalized_chunk_id,
        "doc_id": normalized_doc_id,
        "doc_hash": (doc_hash or "").strip() or default_doc_hash,
        "source_path": normalized_source_path,
        "h1": (h1 or "").strip() or None,
        "h2": (h2 or "").strip() or None,
        "h3": (h3 or "").strip() or None,
        "source_url": (source_url or "").strip() or None,
        "platform": (platform or "").strip() or None,
        "product": (product or "").strip() or None,
        "chunk_index": None,
        "content": normalized_text,
        "metadata": metadata or {},
        "embedding": embedding,
    }
    upsert_chunk_rows(dsn=dsn, table=table, rows=[row])
    latency_ms = int((time.perf_counter() - started) * 1000)
    return normalized_chunk_id, latency_ms


def similarity_search_with_score(
    *,
    dsn: str,
    table: str,
    query_embedding: list[float],
    top_k: int,
    platform: str | None = None,
    product: str | None = None,
) -> list[tuple[RetrievedChunk, float]]:
    if top_k <= 0:
        return []

    psycopg = _import_psycopg()
    sql = psycopg.sql
    vector_param = _vector_literal(query_embedding)
    clauses = [sql.SQL("1=1")]
    params: list[Any] = [vector_param, vector_param]

    if platform and platform.strip():
        clauses.append(sql.SQL("platform = %s"))
        params.append(platform.strip())
    if product and product.strip():
        clauses.append(sql.SQL("product = %s"))
        params.append(product.strip())

    params.append(int(top_k))
    query = sql.SQL(
        """
        SELECT
            id,
            content,
            source_path,
            h1,
            h2,
            h3,
            source_url,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {}
        WHERE {}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """
    ).format(sql.Identifier(table), sql.SQL(" AND ").join(clauses))

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    results: list[tuple[RetrievedChunk, float]] = []
    for row in rows:
        chunk = RetrievedChunk(
            chunk_id=str(row[0]),
            text=str(row[1]),
            score=0.0,
            source_path=str(row[2]),
            h1=(str(row[3]).strip() or None) if row[3] is not None else None,
            h2=(str(row[4]).strip() or None) if row[4] is not None else None,
            h3=(str(row[5]).strip() or None) if row[5] is not None else None,
            source_url=(str(row[6]).strip() or None) if row[6] is not None else None,
        )
        similarity = float(row[7]) if row[7] is not None else 0.0
        results.append((chunk, similarity))
    return results
