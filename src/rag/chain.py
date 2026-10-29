"""Task 7: grounded answer generation with citations.

Findings from the specialist agents become numbered sources:
    S1, S2, ...  document passages (researcher)
    T1, T2, ...  query results over tables (analyst)
The writer may only use these sources and must cite them; citations to labels
that do not exist are removed afterwards.
"""

from __future__ import annotations

import re
from html import escape

from langchain_core.language_models import BaseChatModel

from src.agents import prompts
from src.agents.state import Finding
from src.ingestion.chunking import source_header

CITATION = re.compile(r"\[([ST]\d+)\]")
NOT_FOUND = "I couldn't find this in your documents."
MAX_PASSAGES = 8


def build_sources(findings: list[Finding]) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    passages = 0
    for finding in findings:
        for chunk in finding.get("chunks", []):
            chunk_id = chunk.document.metadata.get("chunk_id")
            if chunk_id in seen or passages >= MAX_PASSAGES:
                continue
            seen.add(chunk_id)
            passages += 1
            sources.append({"label": f"S{passages}", "kind": "passage", "chunk": chunk,
                            "header": source_header(chunk.document.metadata).removeprefix("Source: "),
                            "text": chunk.document.page_content.partition("\n")[2],
                            "untrusted": bool(chunk.document.metadata.get("untrusted"))})
    queries = [q for f in findings for q in f.get("queries", []) if not q.get("error")]
    for i, query in enumerate(queries, 1):
        sources.append({"label": f"T{i}", "kind": "query", "sql": query["sql"],
                        "text": query["markdown"], "header": "data query", "untrusted": False, "query": query})
    return sources


def format_sources(sources: list[dict]) -> str:
    blocks = []
    for s in sources:
        trust = "untrusted-flagged" if s["untrusted"] else "untrusted"
        extra = f' sql="{escape(s["sql"])}"' if s["kind"] == "query" else ""
        blocks.append(f'<source id="{s["label"]}" from="{escape(s["header"])}" trust="{trust}"{extra}>\n'
                      f'{s["text"]}\n</source>')
    return "\n\n".join(blocks) or "(no sources)"


def generate_answer(model: BaseChatModel, question: str, sources: list[dict], feedback: str = "") -> str:
    if not sources:
        return NOT_FOUND
    prompt = prompts.WRITER.format(question=question, sources=format_sources(sources), feedback=feedback)
    return model.invoke(prompt).text.strip()


def clean_citations(answer: str, sources: list[dict]) -> tuple[str, list[str]]:
    """Drop citations to labels that don't exist; return (answer, labels actually cited, in order)."""
    valid = {s["label"] for s in sources}
    cited: list[str] = []

    def keep(match: re.Match) -> str:
        label = match.group(1)
        if label not in valid:
            return ""
        if label not in cited:
            cited.append(label)
        return match.group(0)

    cleaned = CITATION.sub(keep, answer)
    return re.sub(r"[ \t]+([.,;:])", r"\1", cleaned).strip(), cited
