import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.example", ".venv313/.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: Optional[SecretStr] = Field(default=None, alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4.1", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-large", alias="OPENAI_EMBEDDING_MODEL"
    )

    docs_dir: Path = Field(default=Path("doc"), alias="DOCS_DIR")
    pgvector_dsn: Optional[SecretStr] = Field(default=None, alias="PGVECTOR_DSN")
    pgvector_table: str = Field(default="docagent_chunks", alias="PGVECTOR_TABLE")
    pgvector_dim: int = Field(default=3072, alias="PGVECTOR_DIM")

    chunk_size: int = Field(default=900, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=180, alias="CHUNK_OVERLAP")
    retrieval_top_k: int = Field(default=12, alias="RETRIEVAL_TOP_K")
    rerank_top_n: int = Field(default=8, alias="RERANK_TOP_N")
    query_variants: int = Field(default=4, alias="QUERY_VARIANTS")
    retry_max_attempts: int = Field(default=3, alias="RETRY_MAX_ATTEMPTS")
    retry_base_seconds: float = Field(default=0.8, alias="RETRY_BASE_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: Path = Field(default=Path("logs/doc_agent.log"), alias="LOG_FILE")
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    web_session_window: int = Field(default=20, alias="WEB_SESSION_WINDOW")
    web_admin_token: Optional[SecretStr] = Field(default=None, alias="WEB_ADMIN_TOKEN")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_openai_api_key_value() -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    value = settings.openai_api_key.get_secret_value().strip()
    return value or None


def get_pgvector_dsn_value() -> str | None:
    settings = get_settings()
    if settings.pgvector_dsn:
        value = settings.pgvector_dsn.get_secret_value().strip()
        if value:
            return value
    fallback = os.getenv("DATABASE_URL", "").strip()
    return fallback or None
