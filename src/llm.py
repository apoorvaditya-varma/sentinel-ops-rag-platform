"""Factories for every model the system uses.

Two chat models (strong + fast) and three local retrieval models (dense
embeddings, BM25 sparse embeddings, cross-encoder reranker).  Swapping any of
them is a `.env` change, e.g. LLM_MODEL=openai:gpt-5.4-mini.
"""

from __future__ import annotations

from functools import lru_cache

from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_qdrant import FastEmbedSparse

from src.config import get_settings, missing_keys_for
from src.errors import MissingAPIKeyError


class FastEmbedEmbeddings(Embeddings):
    """LangChain adapter over FastEmbed dense models (local ONNX, no torch)."""

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


STRONG_PREF, FAST_PREF = "llm_model", "llm_fast_model"


def effective_models() -> tuple[str, str]:
    """(strong, fast) model strings: Settings-page choice if set, otherwise .env."""
    from src.history import get_history  # local import: history depends on config, not on llm

    settings = get_settings()
    history = get_history()
    return (history.get_pref(STRONG_PREF) or settings.llm_model,
            history.get_pref(FAST_PREF) or settings.llm_fast_model)


def _require_key(model: str) -> None:
    missing = missing_keys_for((model,))
    if missing:
        raise MissingAPIKeyError(detail=f"{model} needs {', '.join(missing)}")


@lru_cache(maxsize=16)
def build_chat_model(model: str, temperature: float) -> BaseChatModel:
    """One cached client per (model, temperature); the cache is cleared when keys change."""
    settings = get_settings()
    return init_chat_model(model, temperature=temperature, timeout=settings.llm_timeout_s, max_retries=1)


def reset_model_cache() -> None:
    build_chat_model.cache_clear()


def get_chat_model() -> BaseChatModel:
    """Strong model: analysis, answer writing."""
    model = effective_models()[0]
    _require_key(model)
    return build_chat_model(model, get_settings().llm_temperature)


def get_fast_chat_model() -> BaseChatModel:
    """Fast model: supervisor plan, passage grading, review, borderline upload screening."""
    model = effective_models()[1]
    _require_key(model)
    return build_chat_model(model, 0.0)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    settings = get_settings()
    return FastEmbedEmbeddings(settings.embedding_model, str(settings.model_cache_dir))


@lru_cache(maxsize=1)
def get_sparse_embeddings() -> FastEmbedSparse:
    settings = get_settings()
    return FastEmbedSparse(model_name=settings.sparse_model, cache_dir=str(settings.model_cache_dir))


@lru_cache(maxsize=1)
def get_reranker() -> TextCrossEncoder:
    settings = get_settings()
    return TextCrossEncoder(model_name=settings.reranker_model, cache_dir=str(settings.model_cache_dir))
