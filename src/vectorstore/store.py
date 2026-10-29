"""Task 5: persistent hybrid vector store on embedded Qdrant (no server).

One collection with two named vectors per chunk:
- `dense`  : bge-small embedding (cosine) for meaning
- `sparse` : BM25 term weights with Qdrant's IDF modifier for exact tokens
             (CVE IDs, hostnames, error codes)
Search runs both branches and fuses them with Reciprocal Rank Fusion.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache, wraps
from pathlib import Path
from typing import Literal

from langchain_core.documents import Document
from qdrant_client import QdrantClient, models

from src.config import get_settings
from src.llm import get_embeddings, get_sparse_embeddings

log = logging.getLogger(__name__)

DENSE, SPARSE = "dense", "sparse"
SearchMode = Literal["hybrid", "dense", "sparse"]


def _locked(method):
    """Serialise access: the web server calls the store from several threads."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class SearchHit:
    document: Document
    score: float  # RRF score for hybrid, similarity / BM25 score otherwise


class KnowledgeStore:
    def __init__(self, path: Path, collection: str) -> None:
        self.client = QdrantClient(path=str(path))
        self.collection = collection
        self._lock = threading.RLock()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        dim = len(get_embeddings().embed_query("dimension probe"))
        self.client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        log.info("Created Qdrant collection %s (dim=%d)", self.collection, dim)

    @_locked
    def add(self, chunks: list[Document]) -> int:
        if not chunks:
            return 0
        texts = [c.page_content for c in chunks]
        dense = get_embeddings().embed_documents(texts)
        sparse = get_sparse_embeddings().embed_documents(texts)
        points = [
            models.PointStruct(
                id=chunk.metadata["chunk_id"],
                vector={DENSE: d, SPARSE: models.SparseVector(indices=s.indices, values=s.values)},
                payload={"text": chunk.page_content, "metadata": chunk.metadata},
            )
            for chunk, d, s in zip(chunks, dense, sparse)
        ]
        self.client.upsert(self.collection, points=points)
        return len(points)

    @_locked
    def search(
        self, query: str, limit: int, mode: SearchMode = "hybrid", sources: list[str] | None = None
    ) -> list[SearchHit]:
        query_filter = None
        if sources:
            query_filter = models.Filter(
                must=[models.FieldCondition(key="metadata.source", match=models.MatchAny(any=sources))]
            )
        dense_query = get_embeddings().embed_query(query) if mode != "sparse" else None
        sparse_query = None
        if mode != "dense":
            s = get_sparse_embeddings().embed_query(query)
            sparse_query = models.SparseVector(indices=s.indices, values=s.values)

        if mode == "hybrid":
            response = self.client.query_points(
                self.collection,
                prefetch=[
                    models.Prefetch(query=dense_query, using=DENSE, filter=query_filter, limit=limit * 2),
                    models.Prefetch(query=sparse_query, using=SPARSE, filter=query_filter, limit=limit * 2),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
        else:
            response = self.client.query_points(
                self.collection,
                query=dense_query if mode == "dense" else sparse_query,
                using=DENSE if mode == "dense" else SPARSE,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        return [
            SearchHit(Document(page_content=p.payload["text"], metadata=p.payload["metadata"]), p.score)
            for p in response.points
        ]

    @_locked
    def delete_source(self, source: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="metadata.source", match=models.MatchValue(value=source))]
                )
            ),
        )

    @_locked
    def sources(self) -> dict[str, int]:
        """Chunk count per indexed source file."""
        counts: Counter[str] = Counter()
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=512, offset=offset, with_payload=["metadata.source"], with_vectors=False
            )
            counts.update(p.payload["metadata"]["source"] for p in points)
            if offset is None:
                return dict(sorted(counts.items()))

    @_locked
    def count(self) -> int:
        return self.client.count(self.collection).count


@lru_cache(maxsize=1)
def get_store() -> KnowledgeStore:
    """Process-wide store: embedded Qdrant allows only one client per folder."""
    settings = get_settings()
    store = KnowledgeStore(settings.qdrant_dir, settings.collection_name)
    atexit.register(store.client.close)  # release the folder lock cleanly
    return store
