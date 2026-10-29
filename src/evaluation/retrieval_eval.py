"""Offline retrieval evaluation: `python -m src.evaluation.retrieval_eval`.

Compares retrieval configurations on data/eval/retrieval_golden.yaml against
the currently indexed corpus (ingest data/sample_docs first).  No LLM needed.

Metrics (answer-bearing chunk, not just the right file):
- hit@1, hit@5 : share of queries whose answer passage is in the top 1 / 5
- MRR@5        : mean reciprocal rank of the first answer-bearing chunk
"""

from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass

import yaml

from src.config import DATA_DIR
from src.retrieval.retriever import retrieve

GOLDEN_PATH = DATA_DIR / "eval" / "retrieval_golden.yaml"

CONFIGS = {
    "dense only": dict(mode="dense", rerank=False),
    "BM25 only": dict(mode="sparse", rerank=False),
    "hybrid (RRF)": dict(mode="hybrid", rerank=False),
    "dense + rerank": dict(mode="dense", rerank=True),
    "hybrid + rerank": dict(mode="hybrid", rerank=True),
}


@dataclass
class ConfigResult:
    name: str
    hit1: float
    hit5: float
    mrr: float
    hit5_by_kind: dict[str, float]
    ms_per_query: float
    misses: list[str]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def load_golden() -> list[dict]:
    return yaml.safe_load(GOLDEN_PATH.read_text())


def evaluate(config: dict, golden: list[dict], k: int = 5) -> tuple[list[int | None], float]:
    ranks, started = [], time.perf_counter()
    for item in golden:
        chunks = retrieve(item["query"], top_k=k, **config)
        answer = _norm(item["answer"])
        rank = next((i for i, c in enumerate(chunks, 1) if answer in _norm(c.document.page_content)), None)
        ranks.append(rank)
    return ranks, (time.perf_counter() - started) * 1000 / len(golden)


def run(k: int = 5) -> list[ConfigResult]:
    golden = load_golden()
    retrieve("warm-up", top_k=1)  # load embedding + reranker models outside the timed loop
    results = []
    for name, config in CONFIGS.items():
        ranks, ms = evaluate(config, golden, k)
        kinds = sorted({g["kind"] for g in golden})
        results.append(
            ConfigResult(
                name=name,
                hit1=statistics.mean(r == 1 for r in ranks),
                hit5=statistics.mean(r is not None for r in ranks),
                mrr=statistics.mean(1 / r if r else 0 for r in ranks),
                hit5_by_kind={
                    kind: statistics.mean(r is not None for r, g in zip(ranks, golden) if g["kind"] == kind)
                    for kind in kinds
                },
                ms_per_query=ms,
                misses=[g["query"] for r, g in zip(ranks, golden) if r is None],
            )
        )
    return results


def main() -> None:
    golden = load_golden()
    results = run()
    kinds = list(results[0].hit5_by_kind)
    print(f"Retrieval evaluation - {len(golden)} queries, answer-bearing chunk in top-k\n")
    header = f"| Config | hit@1 | hit@5 | MRR@5 | " + " | ".join(f"hit@5 {k}" for k in kinds) + " | ms/query |"
    print(header)
    print("|" + "---|" * (header.count("|") - 1))
    for r in results:
        by_kind = " | ".join(f"{r.hit5_by_kind[k]:.0%}" for k in kinds)
        print(f"| {r.name} | {r.hit1:.0%} | {r.hit5:.0%} | {r.mrr:.2f} | {by_kind} | {r.ms_per_query:.0f} |")
    for r in results:
        if r.misses:
            print(f"\nMisses ({r.name}):")
            for q in r.misses:
                print(f"  - {q}")


if __name__ == "__main__":
    main()
