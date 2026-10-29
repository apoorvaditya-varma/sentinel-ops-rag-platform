"""Plain-language presentation helpers: turn internal results into text a
non-technical user understands. Technical values stay available separately for
the collapsible "Technical details" sections."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from markdown_it import MarkdownIt
from markupsafe import Markup

from src.guardrails.domains import DOMAIN_BY_KEY
from src.guardrails.relevance import Verdict
from src.ingestion.screening import ScreeningResult
from src.retrieval.retriever import RetrievedChunk

_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")

VERDICT_LABEL = {
    Verdict.ACCEPTED: ("Added", "ok"),
    Verdict.NEEDS_REVIEW: ("Needs your confirmation", "warn"),
    Verdict.REJECTED: ("Not added", "bad"),
}

FILE_KIND = {
    "pdf": "PDF", "docx": "Word", "md": "Markdown", "txt": "Text", "log": "Log",
    "csv": "Spreadsheet (CSV)", "xlsx": "Spreadsheet", "json": "JSON", "yaml": "YAML", "yml": "YAML",
}


def render_markdown(text: str) -> Markup:
    """Safe Markdown -> HTML (raw HTML in the source is escaped, never rendered)."""
    return Markup(_markdown.render(text or ""))


def render_answer(text: str) -> Markup:
    """Markdown answer with [S1]/[T1] citations turned into small badges."""
    html = str(render_markdown(text))
    return Markup(re.sub(r"\[([ST]\d+)\]", r'<sup class="cite">\1</sup>', html))


def display_name(filename: str) -> str:
    """'information_security_policy.pdf' -> 'Information security policy'."""
    stem = filename.rsplit(".", 1)[0]
    words = re.sub(r"[_\s]+", " ", stem).strip()
    return words[:1].upper() + words[1:] if words else filename


def file_kind(filename_or_type: str) -> str:
    ext = filename_or_type.rsplit(".", 1)[-1].lower()
    return FILE_KIND.get(ext, ext.upper())


def topic_labels(keys: list[str]) -> list[str]:
    return [DOMAIN_BY_KEY[k].label for k in keys if k in DOMAIN_BY_KEY]


def friendly_reason(result: ScreeningResult) -> str:
    if result.verdict is Verdict.ACCEPTED:
        return "Added and ready for questions."
    if result.verdict is Verdict.NEEDS_REVIEW:
        return "This may not be about IT, security or operations. Add it anyway?"
    if result.stage == "duplicate":
        return "This document has already been added."
    if result.stage == "parse":
        return "We couldn't read this file. It may be damaged, empty or password-protected."
    if result.stage == "relevance":
        return "It doesn't look related to IT operations, security or governance, so it wasn't added."
    return "This file can't be added."  # the specific reason is shown as "Why:"


def friendly_warnings(result: ScreeningResult) -> list[str]:
    notes = []
    if result.secrets_found:
        notes.append("Passwords or access keys were found and hidden automatically.")
    if result.injection_passages:
        notes.append("Contains text that tries to give instructions to the AI; it is treated with caution.")
    return notes


def location(meta: dict) -> str:
    parts = []
    if meta.get("page"):
        parts.append(f"page {meta['page']}")
    if meta.get("rows") and meta["rows"] != "schema":
        parts.append(f"rows {meta['rows']}")
    return ", ".join(parts)


def _excerpt(meta: dict, body: str) -> dict:
    """Table row chunks become a small table; everything else stays text."""
    if meta.get("rows") and meta["rows"] != "schema":
        lines = body.splitlines()[1:]
        records = [dict(part.split(": ", 1) for part in line.split("; ") if ": " in part) for line in lines]
        columns = list(dict.fromkeys(k for r in records for k in r))
        if records and columns:
            return {"kind": "table", "columns": columns, "rows": [[r.get(c, "") for c in columns] for r in records]}
    return {"kind": "text", "text": body}


def source_view(chunk: RetrievedChunk) -> dict:
    """JSON-serialisable source for display and for storing in chat history."""
    meta = chunk.document.metadata
    body = chunk.document.page_content.partition("\n")[2]
    return {
        "source": meta["source"],
        "title": display_name(meta["source"]),
        "location": location(meta),
        "untrusted": bool(meta.get("untrusted")),
        "excerpt": _excerpt(meta, body),
        "technical": {
            "file": meta["source"],
            "chunk_id": meta.get("chunk_id"),
            "relevance_score": round(chunk.rerank_score, 3) if chunk.rerank_score is not None else None,
            "search_score": round(chunk.search_score, 4),
        },
    }


def agent_source_view(source: dict, cited: list[str]) -> dict:
    """View for a numbered source the answer writer used (S# passage or T# data query)."""
    if source["kind"] == "passage":
        view = source_view(source["chunk"])
    else:
        query = source["query"]
        view = {
            "source": None, "title": "Data query", "location": "", "untrusted": False,
            "excerpt": {"kind": "table", "columns": query["columns"], "rows": query["rows"]},
            "technical": {"sql": query["sql"], "truncated": query.get("truncated", False)},
        }
    return view | {"label": source["label"], "cited": source["label"] in cited}


def history_groups(conversations, now: datetime | None = None) -> list[tuple[str, list]]:
    """Group conversations as Today / Yesterday / Previous 7 days / Older (local time)."""
    now = (now or datetime.now().astimezone()).astimezone()
    today = now.date()
    groups: dict[str, list] = {"Today": [], "Yesterday": [], "Previous 7 days": [], "Older": []}
    for conversation in conversations:
        day = conversation.updated_at.astimezone().date()
        if day == today:
            groups["Today"].append(conversation)
        elif day == today - timedelta(days=1):
            groups["Yesterday"].append(conversation)
        elif day > today - timedelta(days=7):
            groups["Previous 7 days"].append(conversation)
        else:
            groups["Older"].append(conversation)
    return [(label, items) for label, items in groups.items() if items]


def local_time(value: datetime) -> str:
    return value.astimezone().strftime("%d %b %Y, %H:%M")
