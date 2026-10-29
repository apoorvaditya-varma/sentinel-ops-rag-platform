"""Task 6: hybrid retrieval + cross-encoder reranking.

    query -> hybrid search (dense + BM25, RRF) for FETCH_K candidates
          -> cross-encoder scores every (query, chunk) pair
          -> best TOP_K chunks

The reranker reads query and chunk together, so it judges relevance far
better than either vector score; hybrid search only has to get the right
chunk into the candidate set.

Identifier pinning: cross-encoders do not treat IDs (CVE numbers, IPs,
INC-/DEP-/CHG- tickets, ATT&CK techniques, versions, hostnames) as must-match
tokens and can rank a row with the exact ID below similar-looking rows.  When
the query contains such IDs, chunks containing them verbatim rank first; the
reranker orders within each group.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain_core.documents import Document

from src.config import get_settings
from src.llm import get_reranker
from src.vectorstore.store import SearchMode, get_store


IDENTIFIER_PATTERN = re.compile(
    r"\bCVE-\d{4}-\d{4,}\b"                      # CVE-2024-6387
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"              # IPv4
    r"|\b[A-Z]{2,6}-\d{2,}\b"                    # INC-2041, DEP-1187, CHG-8901, VULN-3001
    r"|\bT\d{4}(?:\.\d{3})?\b"                   # MITRE ATT&CK T1110, T1059.001
    r"|\bv?\d+\.\d+\.\d+\b"                      # versions 2.14.0
    r"|\b[a-z]+(?:-[a-z0-9]+)*-\d{2,}\b",        # hostnames payments-db-07
    re.IGNORECASE,
)


def query_identifiers(query: str) -> set[str]:
    return {m.group(0).lower() for m in IDENTIFIER_PATTERN.finditer(query)}


@dataclass
class RetrievedChunk:
    document: Document
    search_score: float
    rerank_score: float | None

    @property
    def source(self) -> str:
        return self.document.metadata["source"]


def retrieve(
    query: str,
    top_k: int | None = None,
    fetch_k: int | None = None,
    sources: list[str] | None = None,
    mode: SearchMode = "hybrid",
    rerank: bool = True,
) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.top_k
    fetch_k = fetch_k or settings.fetch_k

    hits = get_store().search(query, limit=fetch_k if rerank else top_k, mode=mode, sources=sources)
    if not hits:
        return []
    if not rerank:
        return [RetrievedChunk(h.document, h.score, None) for h in hits[:top_k]]

    scores = list(get_reranker().rerank(query, [h.document.page_content for h in hits]))
    identifiers = query_identifiers(query)

    def sort_key(pair) -> tuple[int, float]:
        hit, score = pair
        text = hit.document.page_content.lower()
        return sum(ident in text for ident in identifiers), score

    ranked = sorted(zip(hits, scores), key=sort_key, reverse=True)
    return [RetrievedChunk(hit.document, hit.score, float(score)) for hit, score in ranked[:top_k]]
