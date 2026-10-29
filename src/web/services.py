"""Application services shared by the HTML pages and the REST API."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from src.config import get_settings, missing_keys_for, sample_documents
from src.agents.graph import default_models, run_agents
from src.agents.registry import ALL_AGENTS
from src.errors import CancelledError, NotFoundError, UserInputError, report
from src.guardrails.content_scan import redact_secrets
from src.guardrails.query_guard import BLOCKED_REPLY, MAX_QUESTION_CHARS, check_question
from src.guardrails.relevance import Verdict
from src.history import get_history
from src.ingestion.pipeline import IngestReport, ingest_file, remove_file
from src.ingestion.screening import ScreeningResult, discard, promote, screen_upload
from src.retrieval.retriever import retrieve
from src.llm import effective_models
from src.logging_setup import audit
from src.vectorstore.store import get_store
from src.web.presenters import (
    agent_source_view, display_name, file_kind, friendly_reason, friendly_warnings, source_view, topic_labels,
)

log = logging.getLogger(__name__)

LAST_CONVERSATION_PREF = "last_conversation"


class InFlight:
    """Questions being answered right now, so Stop can cancel them and a revisited
    conversation can show "still writing". Single-user app: process memory is enough."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, token: str, conversation_id: str | None) -> threading.Event:
        cancel = threading.Event()
        with self._lock:
            self._jobs[token] = {"cancel": cancel, "conversation_id": conversation_id}
        return cancel

    def attach(self, token: str, conversation_id: str) -> None:
        with self._lock:
            if token in self._jobs:
                self._jobs[token]["conversation_id"] = conversation_id

    def finish(self, token: str) -> None:
        with self._lock:
            self._jobs.pop(token, None)

    def cancel(self, token: str) -> bool:
        with self._lock:
            job = self._jobs.get(token)
        if job is None:
            return False
        job["cancel"].set()
        return True

    def running(self, token: str) -> bool:
        with self._lock:
            return token in self._jobs

    def token_for(self, conversation_id: str) -> str | None:
        with self._lock:
            return next((t for t, j in self._jobs.items() if j["conversation_id"] == conversation_id), None)


INFLIGHT = InFlight()

# Files waiting for the user's "add anyway?" decision.  Single-user local app,
# so process memory is enough; staged copies live in data/uploads/.staging.
_PENDING: dict[str, ScreeningResult] = {}


CHECK_LABEL = {
    "file_type": "File type check", "duplicate": "Duplicate check",
    "parse": "Readability check", "relevance": "Topic check",
}


@dataclass
class UploadOutcome:
    filename: str
    status: str            # added | needs_review | rejected | error
    tone: str              # ok | warn | bad
    message: str
    why: str | None = None  # the specific check and cause, shown for files that were not added
    warnings: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    pending_id: str | None = None
    technical: dict = field(default_factory=dict)


AI_ANSWERS_PREF = "ai_answers"


def ai_answers_wanted() -> bool:
    return get_history().get_pref(AI_ANSWERS_PREF, "true") == "true"


def ai_enabled() -> bool:
    """AI-written answers need a key for the chosen models and the switch on; otherwise passages are shown."""
    return ai_answers_wanted() and not missing_keys_for(effective_models())


# ---- documents ---------------------------------------------------------------
def _outcome(result: ScreeningResult, report_: IngestReport | None = None) -> UploadOutcome:
    status = {Verdict.ACCEPTED: "added", Verdict.NEEDS_REVIEW: "needs_review", Verdict.REJECTED: "rejected"}
    tone = {Verdict.ACCEPTED: "ok", Verdict.NEEDS_REVIEW: "warn", Verdict.REJECTED: "bad"}
    technical = {
        "file": result.filename, "check": CHECK_LABEL.get(result.stage, result.stage), "detail": result.reason,
        "size_kb": round(result.size_bytes / 1024, 1) if result.size_bytes else None,
        "topic_score": result.relevance_margin, "decided_by": result.method or None,
        "warnings": result.warnings or None,
    }
    if report_:
        technical |= {"chunks": report_.chunks, "tables": report_.tables or None}
    message = friendly_reason(result)
    why = None
    if result.verdict is not Verdict.ACCEPTED and result.reason.rstrip(".") not in message:
        why = f"{CHECK_LABEL.get(result.stage, 'Check')}: {result.reason}"
    return UploadOutcome(
        filename=result.filename,
        status=status[result.verdict],
        tone=tone[result.verdict],
        message=message,
        why=why,
        warnings=friendly_warnings(result),
        topics=topic_labels(result.domains),
        pending_id=result.sha256 if result.verdict is Verdict.NEEDS_REVIEW else None,
        technical={k: v for k, v in technical.items() if v is not None},
    )


def _index(result: ScreeningResult) -> IngestReport:
    report_ = ingest_file(promote(result))
    get_history().record_document(
        result.filename, result.filename.rsplit(".", 1)[-1].lower(), topic_labels(result.domains),
        report_.chunks, report_.tables, friendly_warnings(result),
    )
    return report_


def add_files(files: list[tuple[str, bytes]]) -> list[UploadOutcome]:
    """Screen and index each file; one bad file never fails the whole batch."""
    history = get_history()
    outcomes = []
    for name, data in files:
        try:
            result = screen_upload(name, data)
            report_ = None
            if result.verdict is Verdict.ACCEPTED:
                report_ = _index(result)
            elif result.verdict is Verdict.NEEDS_REVIEW:
                _PENDING[result.sha256] = result
            outcome = _outcome(result, report_)
        except Exception as exc:  # noqa: BLE001 - reported per file
            error = report(exc, f"adding {name}", log)
            outcome = UploadOutcome(name, "error", "bad", error.user_message,
                                    why=redact_secrets(error.detail) or None,
                                    technical={"error_code": error.code, "reference": error.reference})
        history.log_upload(outcome.filename, outcome.status, outcome.why or outcome.message, outcome.technical)
        outcomes.append(outcome)
    return outcomes


def add_sample_documents() -> list[UploadOutcome]:
    samples = sample_documents()
    return add_files([(p.name, p.read_bytes()) for p in samples])


def resolve_pending(pending_id: str, accept: bool) -> UploadOutcome:
    result = _PENDING.pop(pending_id, None)
    if result is None:
        raise NotFoundError("This upload is no longer waiting for a decision.", hint="Upload the file again.")
    if not accept:
        discard(result)
        outcome = UploadOutcome(result.filename, "rejected", "bad", "Not added, as you chose.")
    else:
        result.verdict = Verdict.ACCEPTED
        outcome = _outcome(result, _index(result))
        outcome.message = "Added at your request."
    get_history().log_upload(outcome.filename, outcome.status, outcome.message)
    return outcome


def pending_uploads() -> list[UploadOutcome]:
    return [_outcome(result) for result in _PENDING.values()]


def list_documents() -> list[dict]:
    indexed = get_store().sources()
    catalogue = get_history().documents()
    documents = []
    for source, chunks in indexed.items():
        info = catalogue.get(source, {})
        documents.append({
            "source": source,
            "title": display_name(source),
            "kind": file_kind(source),
            "topics": info.get("topics", []),
            "warnings": info.get("warnings", []),
            "added_at": info.get("added_at"),
            "technical": {"file": source, "chunks": chunks, "tables": info.get("tables") or None},
        })
    return sorted(documents, key=lambda d: d["title"].lower())


def remove_document(source: str) -> None:
    if source not in get_store().sources():
        raise NotFoundError("That document is not in the knowledge base.",
                            detail=f"No indexed document named '{source}' (it may already have been removed).")
    remove_file(source)
    history = get_history()
    history.forget_document(source)
    history.log_upload(source, "removed", "Removed from the knowledge base.")


# ---- questions ---------------------------------------------------------------
@dataclass
class AskResult:
    conversation_id: str
    created: bool
    question: str
    answer: str
    sources: list[dict]
    mode: str  # answer | preview | empty | blocked
    meta: dict = field(default_factory=dict)


def get_models():
    """Hook for tests; returns the strong + fast chat models."""
    return default_models()


def _preview(question: str, scope: list[str] | None, indexed: dict) -> tuple[str, list[dict]]:
    chunks = retrieve(question, sources=[s for s in (scope or []) if s in indexed] or None)
    sources = [source_view(c) for c in chunks]
    if not sources:
        return "I couldn't find anything about that in your documents.", []
    top = sources[0]
    top["featured"] = True  # preview mode: show the best passage inline, not only under Sources
    where = f"{top['title']}" + (f", {top['location']}" if top["location"] else "")
    reason = ("AI answers are switched off in Settings" if not ai_answers_wanted()
              else "no API key is set for the chosen models (see Settings)")
    return (f"Because {reason}, here is the most relevant passage from your documents "
            f"(**{where}**). More matches are listed under *Sources*."), sources


def ask(question: str, conversation_id: str | None = None, scope: list[str] | None = None,
        cancel: threading.Event | None = None, token: str | None = None) -> AskResult:
    started = time.perf_counter()
    check = check_question(question)
    if not check.allowed and check.reason == "empty":
        raise UserInputError("Please type a question.")
    if not check.allowed and check.reason == "too_long":
        raise UserInputError(f"Please keep questions under {MAX_QUESTION_CHARS} characters.")

    history = get_history()
    created = not (conversation_id and history.conversation_exists(conversation_id))
    if created:
        conversation_id = history.create_conversation(check.question)
    previous = [{"role": m["role"], "content": m["content"]} for m in history.messages(conversation_id)]
    history.add_message(conversation_id, "user", check.question)
    history.set_pref(LAST_CONVERSATION_PREF, conversation_id)  # the Ask tab returns here, even mid-answer
    if token:
        INFLIGHT.attach(token, conversation_id)

    meta: dict = {"notes": check.notes} if check.notes else {}
    indexed = get_store().sources()
    if not check.allowed:
        audit("question_blocked", reason=check.reason, question=check.question[:300])
        answer, sources, mode = BLOCKED_REPLY, [], "blocked"
    elif not indexed:
        answer, sources, mode = (
            "Your knowledge base is empty. Add documents on the **Documents** page, then ask again.", [], "empty"
        )
    elif ai_enabled():
        try:
            result = run_agents(check.question, previous, [s for s in (scope or []) if s in indexed] or None,
                                models=get_models(), cancel=cancel)
            answer, mode = result.answer, "answer"
            sources = [agent_source_view(s, result.cited) for s in result.sources]
            meta |= {
                "models": list(effective_models()),
                "agents": result.agents_used, "intent": result.intent, "caveat": result.caveat,
                "standalone_question": result.question,
                "trace": [dict(step, title=ALL_AGENTS[step["agent"]].title) for step in result.trace],
            }
        except CancelledError:
            history.add_message(conversation_id, "assistant", "Stopped before an answer was ready.",
                                meta={"mode": "cancelled", "seconds": round(time.perf_counter() - started, 1)})
            raise
        except Exception as exc:  # noqa: BLE001 - fall back to showing passages
            error = report(exc, "answering with agents", log)
            answer, sources = _preview(check.question, scope, indexed)
            mode = "preview"
            meta["notice"] = f"{error.user_message} Showing the most relevant passages instead (ref {error.reference})."
    else:
        answer, sources = _preview(check.question, scope, indexed)
        mode = "preview"

    meta["mode"] = mode
    meta["seconds"] = round(time.perf_counter() - started, 1)
    history.add_message(conversation_id, "assistant", answer, sources, meta)
    return AskResult(conversation_id, created, check.question, answer, sources, mode, meta)
