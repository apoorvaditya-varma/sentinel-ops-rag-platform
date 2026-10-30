"""Central configuration, loaded once from environment variables / `.env`."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from src.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")

_KEY_BY_PROVIDER = {
    "google_genai": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def provider_of(model: str) -> str:
    return model.split(":", 1)[0] if ":" in model else ""


@dataclass(frozen=True)
class Settings:
    app_name: str
    log_level: str
    log_dir: Path
    log_to_file: bool
    log_rotation: str
    log_max_mb: int
    log_backup_count: int
    log_rotate_when: str
    log_format: str

    llm_model: str
    llm_fast_model: str
    llm_temperature: float

    embedding_model: str
    sparse_model: str
    reranker_model: str
    model_cache_dir: Path

    chunk_size: int
    chunk_overlap: int
    fetch_k: int
    top_k: int
    max_retrieval_retries: int
    max_answer_retries: int
    agent_recursion_limit: int
    llm_timeout_s: int
    llm_retry_attempts: int
    collection_name: str

    web_host: str
    web_port: int
    max_upload_mb: int
    max_pdf_pages: int
    relevance_accept_margin: float
    relevance_reject_margin: float
    allow_relevance_override: bool
    upload_dir: Path
    staging_dir: Path
    qdrant_dir: Path
    tables_db: Path
    history_db: Path
    sample_docs_dir: Path

    @property
    def log_level_no(self) -> int:
        return logging.getLevelName(self.log_level)

    def missing_api_keys(self, models: tuple[str, ...] | None = None) -> list[str]:
        """Env vars required by the given (default: configured) LLM providers that are not set."""
        return missing_keys_for(models or (self.llm_model, self.llm_fast_model))


def missing_keys_for(models) -> list[str]:
    needed = {_KEY_BY_PROVIDER[p] for p in (provider_of(m) for m in models) if p in _KEY_BY_PROVIDER}
    return sorted(var for var in needed if not os.getenv(var, "").strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        settings = _load()
    except ValueError as exc:
        raise ConfigError(detail=str(exc), hint=f"Fix the value in .env: {exc}") from exc
    _validate(settings)
    for path in (settings.staging_dir, settings.qdrant_dir, settings.model_cache_dir):
        path.mkdir(parents=True, exist_ok=True)
    return settings


def _load() -> Settings:
    return Settings(
        app_name=_env("APP_NAME", "Sentinel Ops RAG Platform"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        log_dir=Path(_env("LOG_DIR", str(PROJECT_ROOT / "logs"))),
        log_to_file=_env("LOG_TO_FILE", "true").lower() == "true",
        log_rotation=_env("LOG_ROTATION", "size").lower(),
        log_max_mb=int(_env("LOG_MAX_MB", "10")),
        log_backup_count=int(_env("LOG_BACKUP_COUNT", "5")),
        log_rotate_when=_env("LOG_ROTATE_WHEN", "midnight"),
        log_format=_env("LOG_FORMAT", "text").lower(),
        llm_model=_env("LLM_MODEL", "google_genai:gemini-3.8-flash"),
        llm_fast_model=_env("LLM_FAST_MODEL", "google_genai:gemini-3.5-flash-lite"),
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.1")),
        embedding_model=_env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        sparse_model=_env("SPARSE_MODEL", "Qdrant/bm25"),
        reranker_model=_env("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"),
        model_cache_dir=PROJECT_ROOT / ".cache" / "fastembed",
        chunk_size=int(_env("CHUNK_SIZE", "1000")),
        chunk_overlap=int(_env("CHUNK_OVERLAP", "150")),
        fetch_k=int(_env("FETCH_K", "20")),
        top_k=int(_env("TOP_K", "5")),
        max_retrieval_retries=int(_env("MAX_RETRIEVAL_RETRIES", "2")),
        max_answer_retries=int(_env("MAX_ANSWER_RETRIES", "1")),
        agent_recursion_limit=int(_env("AGENT_RECURSION_LIMIT", "25")),
        llm_timeout_s=int(_env("LLM_TIMEOUT_S", "30")),
        llm_retry_attempts=int(_env("LLM_RETRY_ATTEMPTS", "4")),
        collection_name=_env("COLLECTION_NAME", "ops_knowledge"),
        web_host=_env("WEB_HOST", "127.0.0.1"),
        web_port=int(_env("WEB_PORT", "7400")),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "25")),
        max_pdf_pages=int(_env("MAX_PDF_PAGES", "300")),
        relevance_accept_margin=float(_env("RELEVANCE_ACCEPT_MARGIN", "0.05")),
        relevance_reject_margin=float(_env("RELEVANCE_REJECT_MARGIN", "0.0")),
        allow_relevance_override=_env("ALLOW_RELEVANCE_OVERRIDE", "true").lower() == "true",
        upload_dir=DATA_DIR / "uploads",
        staging_dir=DATA_DIR / "uploads" / ".staging",
        qdrant_dir=DATA_DIR / "qdrant",
        tables_db=DATA_DIR / "tables.duckdb",
        history_db=DATA_DIR / "app.db",
        sample_docs_dir=DATA_DIR / "sample_docs",
    )


def _validate(settings: Settings) -> None:
    problems = []
    if settings.chunk_overlap >= settings.chunk_size:
        problems.append("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
    if settings.top_k > settings.fetch_k:
        problems.append("TOP_K must not exceed FETCH_K")
    if settings.relevance_reject_margin > settings.relevance_accept_margin:
        problems.append("RELEVANCE_REJECT_MARGIN must not exceed RELEVANCE_ACCEPT_MARGIN")
    if not isinstance(settings.log_level_no, int):
        problems.append(f"LOG_LEVEL '{settings.log_level}' is not a logging level (DEBUG/INFO/WARNING/ERROR)")
    if settings.log_rotation not in ("size", "time", "off"):
        problems.append(f"LOG_ROTATION must be size, time or off (got '{settings.log_rotation}')")
    if settings.log_format not in ("text", "json"):
        problems.append(f"LOG_FORMAT must be text or json (got '{settings.log_format}')")
    if problems:
        raise ConfigError(detail="; ".join(problems), hint="Fix in .env: " + "; ".join(problems))


def sample_documents() -> list[Path]:
    """The demo corpus: top-level files in data/sample_docs (subfolders and hidden files like .DS_Store excluded)."""
    folder = get_settings().sample_docs_dir
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
