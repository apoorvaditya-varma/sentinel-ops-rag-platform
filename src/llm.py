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

from src.config import get_settings
from src.errors import MissingAPIKeyError


class FastEmbedEmbeddings(Embeddings):
    """LangChain adapter over FastEmbed dense models (local ONNX, no torch)."""

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


def _require_keys() -> None:
    missing = get_settings().missing_api_keys()
    if missing:
        raise MissingAPIKeyError(detail=f"missing {', '.join(missing)}")


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """Strong model: planning, synthesis, table analysis."""
    _require_keys()
    settings = get_settings()
    return init_chat_model(settings.llm_model, temperature=settings.llm_temperature,
                           timeout=settings.llm_timeout_s, max_retries=1)  # our retry_transient handles the rest


@lru_cache(maxsize=1)
def get_fast_chat_model() -> BaseChatModel:
    """Cheap model: routing, relevance grading, groundedness checks."""
    _require_keys()
    settings = get_settings()
    return init_chat_model(settings.llm_fast_model, temperature=0, timeout=settings.llm_timeout_s, max_retries=1)


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
