"""Answer-quality evaluation of the multi-agent pipeline: `python -m src.evaluation.answer_eval`.

Requires an LLM API key and the sample corpus indexed (python -m scripts.ingest data/sample_docs).

Deterministic metrics (no judge needed):
    fact recall      expected facts present in the answer
    numeric truth    values computed by `truth_sql` on the indexed tables appear in the answer
    source hit       a cited passage comes from an expected file
    routing          the supervisor used the expected specialists / intent
    citation rate    answers cite at least one source
LLM-judged metrics (RAGAS-style, fast model as judge):
    faithfulness     claims supported by the sources the writer saw (0-1)
    relevance        the answer addresses the question (0-1)
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

import yaml
from pydantic import BaseModel, Field

from src.agents import prompts
from src.agents.graph import Models, default_models, run_agents
from src.config import DATA_DIR, get_settings
from src.guardrails.query_guard import check_question
from src.rag.chain import format_sources
from src.tables.sql_store import TableStore, get_table_store

GOLDEN_PATH = DATA_DIR / "eval" / "answer_golden.yaml"
RESULTS_DIR = DATA_DIR / "eval" / "results"


class Judgement(BaseModel):
    faithfulness: float = Field(ge=0, le=1, description="Share of the answer's claims supported by the sources")
    relevance: float = Field(ge=0, le=1, description="How well the answer addresses the question")
    reason: str = ""


@dataclass
class ItemResult:
    question: str
    intent_ok: bool
    agents_ok: bool | None = None
    fact_recall: float | None = None
    numeric_ok: bool | None = None
    source_hit: bool | None = None
    cited: bool | None = None
    faithfulness: float | None = None
    relevance: float | None = None
    seconds: float = 0.0
    answer: str = ""
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().replace("’", "'")


def _has(answer: str, fact: str) -> bool:
    return any(_norm(option) in _norm(answer) for option in fact.split("|"))


def _value_strings(value) -> list[str]:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return [str(value)]


def evaluate_item(item: dict, models: Models, tables: TableStore, judge: bool = True) -> ItemResult:
    question = item["question"]
    expected_intent = item.get("intent", "answer")
    check = check_question(question)
    if not check.allowed:
        return ItemResult(question, intent_ok=expected_intent == "blocked", answer="(blocked by question guard)")

    started = time.perf_counter()
    result = run_agents(check.question, models=models, tables=tables)
    out = ItemResult(question, intent_ok=result.intent == expected_intent, answer=result.answer,
                     seconds=round(time.perf_counter() - started, 2))
    if expected_intent != "answer":
        return out

    if "agents" in item:
        out.agents_ok = set(item["agents"]) <= set(result.agents_used)
    if "facts" in item:
        out.fact_recall = statistics.mean(_has(result.answer, f) for f in item["facts"])
    if "truth_sql" in item:
        row = tables.run_query(item["truth_sql"]).rows[0]
        values = [v for v in row if v is not None]
        out.numeric_ok = all(any(s in result.answer for s in _value_strings(v)) for v in values)
        out.notes.append(f"truth={list(row)}")
    if "sources" in item:
        cited_files = {s["chunk"].document.metadata["source"] for s in result.sources
                       if s["kind"] == "passage" and s["label"] in result.cited}
        out.source_hit = bool(cited_files & set(item["sources"]))
    out.cited = bool(result.cited)

    if judge and result.sources:
        prompt = prompts.JUDGE.format(question=question, sources=format_sources(result.sources), answer=result.answer)
        verdict: Judgement = models.fast.with_structured_output(Judgement).invoke(prompt)
        out.faithfulness, out.relevance = verdict.faithfulness, verdict.relevance
        if verdict.reason:
            out.notes.append(f"judge: {verdict.reason}")
    return out


def summarise(results: list[ItemResult]) -> dict:
    results = [r for r in results if r.error is None]

    def mean(attr):
        values = [getattr(r, attr) for r in results if getattr(r, attr) is not None]
        return round(statistics.mean(float(v) for v in values), 3) if values else None

    return {
        "questions": len(results),
        "intent_accuracy": mean("intent_ok"),
        "routing_accuracy": mean("agents_ok"),
        "fact_recall": mean("fact_recall"),
        "numeric_accuracy": mean("numeric_ok"),
        "source_hit_rate": mean("source_hit"),
        "citation_rate": mean("cited"),
        "faithfulness": mean("faithfulness"),
        "answer_relevance": mean("relevance"),
        "avg_seconds": mean("seconds"),
    }


def _safe_evaluate(item: dict, models: Models, tables: TableStore, judge: bool) -> ItemResult:
    """One question; a provider failure (e.g. quota) is recorded, not fatal."""
    from src.errors import report

    try:
        return evaluate_item(item, models, tables, judge)
    except Exception as exc:  # noqa: BLE001 - keep going with the other questions
        error = report(exc, f"evaluating {item['question'][:40]!r}")
        return ItemResult(item["question"], intent_ok=False, error=f"{error.code}: {error.user_message}")


def run(models: Models | None = None, tables: TableStore | None = None, limit: int | None = None,
        judge: bool = True, pause: float = 0.0, done: dict[str, ItemResult] | None = None,
        on_result=None) -> tuple[list[ItemResult], dict]:
    golden = yaml.safe_load(GOLDEN_PATH.read_text())[:limit]
    models = models or default_models()
    tables = tables or get_table_store()
    results = []
    for index, item in enumerate(golden):
        previous = (done or {}).get(item["question"])
        if previous is not None and previous.error is None:
            results.append(previous)
            continue
        if index and pause:
            time.sleep(pause)
        result = _safe_evaluate(item, models, tables, judge)
        results.append(result)
        if on_result:
            on_result(result)
    return results, summarise(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="evaluate only the first N questions")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM-judged metrics")
    parser.add_argument("--pause", type=float, default=20.0,
                        help="seconds between questions, to stay under free-tier per-minute limits (default 20)")
    parser.add_argument("--resume", action="store_true",
                        help="reuse successful results from the most recent run; redo only failed/missing ones")
    parser.add_argument("--strong", help="override the answer model for this run, e.g. google_genai:gemini-3.6-flash")
    parser.add_argument("--fast", help="override the fast model for this run")
    args = parser.parse_args()
    if args.strong or args.fast:
        import src.llm as llm_module

        strong, fast = llm_module.effective_models()
        chosen = (args.strong or strong, args.fast or fast)
        llm_module.effective_models = lambda: chosen  # noqa: E731 - run-scoped override
    done: dict[str, ItemResult] = {}
    if args.resume:
        previous = sorted(RESULTS_DIR.glob("answer_eval_*.json"))
        if previous:
            for row in json.loads(previous[-1].read_text())["results"]:
                done[row["question"]] = ItemResult(**row)
            print(f"Resuming from {previous[-1].name}: {sum(1 for r in done.values() if r.error is None)} already done")
    from src.config import missing_keys_for
    from src.llm import effective_models

    if missing := missing_keys_for(effective_models()):
        print(f"Set {', '.join(missing)} in .env first: this evaluation calls the LLM.")
        return 2

    def progress(result: ItemResult) -> None:
        state = f"ERROR {result.error}" if result.error else f"ok in {result.seconds}s"
        print(f"  - {result.question[:60]} … {state}", flush=True)

    results, summary = run(limit=args.limit, judge=not args.no_judge, pause=args.pause, done=done,
                           on_result=progress)
    failed = [r for r in results if r.error]
    print(f"\nAnswer evaluation - {summary['questions']} questions"
          + (f", {len(failed)} failed (rerun with --resume)" if failed else "") + "\n")
    print("| Question | Intent | Agents | Facts | Numbers | Source | Faithful | Relevant | s |")
    print("|---|---|---|---|---|---|---|---|---|")
    fmt = lambda v: "—" if v is None else ("✓" if v is True else "✗" if v is False else f"{v:.2f}")  # noqa: E731
    for r in results:
        if r.error:
            print(f"| {r.question[:55]} | ERROR: {r.error[:60]} | | | | | | | |")
            continue
        print(f"| {r.question[:55]} | {fmt(r.intent_ok)} | {fmt(r.agents_ok)} | {fmt(r.fact_recall)} | "
              f"{fmt(r.numeric_ok)} | {fmt(r.source_hit)} | {fmt(r.faithfulness)} | {fmt(r.relevance)} | {r.seconds} |")
    print("\nSummary:", json.dumps(summary, indent=2))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"answer_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "results": [asdict(r) for r in results],
                               "models": list(effective_models())}, indent=2))
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
