"""HTML pages and HTMX partials."""

from __future__ import annotations

import os
import re
import time
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from src.config import get_settings, missing_keys_for
from src.env_file import set_env_value
from src.errors import UserInputError, classify_exception
from src.guardrails.domains import DOMAINS
from src.guardrails.file_validation import ALLOWED_TYPES
from src.history import get_history
from src.llm import FAST_PREF, STRONG_PREF, build_chat_model, effective_models, reset_model_cache
from src.logging_setup import audit
from src.model_registry import PROVIDERS, mask_key, model_catalogue, split_model
from src.web import services
from src.web.presenters import file_kind, history_groups
from src.web.rendering import is_htmx, render

router = APIRouter(include_in_schema=False)

LAST_CONVERSATION_PREF = services.LAST_CONVERSATION_PREF


def remember_conversation(conversation_id: str | None) -> None:
    get_history().set_pref(LAST_CONVERSATION_PREF, conversation_id or "")


def last_conversation_url() -> str:
    """Where the Ask tab goes: the conversation the user was last in, if it still exists."""
    history = get_history()
    conversation_id = history.get_pref(LAST_CONVERSATION_PREF, "")
    return f"/c/{conversation_id}" if conversation_id and history.conversation_exists(conversation_id) else "/"


_TOKEN_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

STARTER_QUESTIONS = [
    "What is the patch deadline for critical vulnerabilities?",
    "What should I do if an AWS access key is leaked?",
    "What caused the payment API outage (INC-2041)?",
    "How do I fix a pod stuck in CrashLoopBackOff?",
]


def _show_technical() -> bool:
    return get_history().get_pref("show_technical", "true") == "true"


def _chat_context(conversation_id: str | None) -> dict:
    history = get_history()
    return {
        "conversation_id": conversation_id,
        "answer_in_progress": bool(conversation_id and services.INFLIGHT.token_for(conversation_id)),
        "messages": history.messages(conversation_id) if conversation_id else [],
        "history": history_groups(history.conversations()),
        "documents": services.list_documents(),
        "starters": STARTER_QUESTIONS,
        "show_technical": _show_technical(),
    }


@router.get("/", response_class=HTMLResponse)
def ask_page(request: Request):
    remember_conversation(None)  # "New chat": the Ask tab now starts fresh until a question is asked
    return render(request, "ask.html", page="ask", **_chat_context(None))


@router.get("/c/{conversation_id}", response_class=HTMLResponse)
def conversation_page(request: Request, conversation_id: str):
    if not get_history().conversation_exists(conversation_id):
        return RedirectResponse("/", status_code=303)
    remember_conversation(conversation_id)
    return render(request, "ask.html", page="ask", **_chat_context(conversation_id))


async def ask_cancellable(request: Request, question: str, conversation_id: str | None, scope: list[str],
                          token: str | None = None):
    """Answer in a worker thread. The work continues even if the browser leaves the page (the
    answer is saved to the conversation); only an explicit Stop (POST /ask/stop) cancels it."""
    token = token or uuid.uuid4().hex
    cancel = services.INFLIGHT.start(token, conversation_id or None)
    try:
        return await run_in_threadpool(services.ask, question, conversation_id, scope, cancel, token)
    finally:
        services.INFLIGHT.finish(token)


@router.post("/ask", response_class=HTMLResponse)
async def ask(request: Request, question: str = Form(""), conversation_id: str = Form(""),
              scope: list[str] = Form(default_factory=list), ask_token: str = Form("")):
    token = ask_token if _TOKEN_RE.match(ask_token or "") else None
    result = await ask_cancellable(request, question, conversation_id or None, scope, token)
    response = render(
        request, "partials/exchange.html",
        result=result, history=history_groups(get_history().conversations()),
        conversation_id=result.conversation_id, show_technical=_show_technical(),
    )
    if result.created:
        response.headers["HX-Push-Url"] = f"/c/{result.conversation_id}"
    return response


@router.post("/ask/stop", response_class=HTMLResponse)
def stop_question(ask_token: str = Form(...)):
    """The Stop button: cancel the agents working on this question."""
    stopped = services.INFLIGHT.cancel(ask_token)
    return HTMLResponse("stopping" if stopped else "not running")


@router.get("/c/{conversation_id}/wait", response_class=HTMLResponse)
def wait_for_answer(conversation_id: str):
    """Polled by a revisited conversation whose answer is still being written."""
    if services.INFLIGHT.token_for(conversation_id):
        return HTMLResponse("", status_code=204)
    response = HTMLResponse("", status_code=286)  # 286 tells HTMX to stop polling
    response.headers["HX-Refresh"] = "true"
    return response


@router.delete("/c/{conversation_id}", response_class=HTMLResponse)
def delete_conversation(request: Request, conversation_id: str, current: str = ""):
    get_history().delete_conversation(conversation_id)
    if get_history().get_pref(LAST_CONVERSATION_PREF, "") == conversation_id:
        remember_conversation(None)
    if current == conversation_id:
        response = HTMLResponse("")
        response.headers["HX-Redirect"] = "/"
        return response
    return render(request, "partials/history.html",
                  history=history_groups(get_history().conversations()), conversation_id=current)


# ---- documents ---------------------------------------------------------------
def _documents_context() -> dict:
    return {
        "documents": services.list_documents(),
        "pending": services.pending_uploads(),
        "uploads": get_history().uploads(limit=50),
        "allowed_types": {ext: (file_kind(ext), t.examples) for ext, t in ALLOWED_TYPES.items()},
        "domains": DOMAINS,
        "max_mb": get_settings().max_upload_mb,
    }


@router.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request):
    return render(request, "documents.html", page="documents", **_documents_context())


async def read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    limit = get_settings().max_upload_mb * 1024 * 1024
    payload = []
    for f in files:
        if not f.filename:
            continue
        data = await f.read(limit + 1)  # read at most one byte past the limit
        payload.append((f.filename, data))
    if not payload:
        raise UserInputError("Choose at least one file to add.",
                             hint="Click “Choose files” or drag files onto the box, then press Add documents.",
                             detail="The upload request contained no files.")
    return payload


@router.post("/documents/upload", response_class=HTMLResponse)
async def upload(request: Request, files: list[UploadFile] = File(default_factory=list)):
    outcomes = services.add_files(await read_uploads(files))
    return render(request, "partials/upload_outcomes.html", outcomes=outcomes, **_documents_context())


@router.post("/documents/samples", response_class=HTMLResponse)
def add_samples(request: Request):
    outcomes = services.add_sample_documents()
    return render(request, "partials/upload_outcomes.html", outcomes=outcomes, **_documents_context())


@router.post("/documents/pending/{pending_id}", response_class=HTMLResponse)
def resolve_pending(request: Request, pending_id: str, decision: str = Form(...)):
    outcome = services.resolve_pending(pending_id, accept=decision == "add")
    return render(request, "partials/upload_outcomes.html", outcomes=[outcome], **_documents_context())


@router.post("/documents/remove", response_class=HTMLResponse)
def remove_document(request: Request, source: str = Form(...)):
    services.remove_document(source)
    return render(request, "partials/documents_area.html", **_documents_context())


# ---- settings ----------------------------------------------------------------
def _recent_errors(lines: int = 30) -> list[str]:
    path = get_settings().log_dir / "errors.log"
    if not path.exists():
        return []
    entries = [line for line in path.read_text(errors="replace").splitlines() if line[:4].isdigit() or line.startswith("{")]
    return entries[-lines:]


def _models_context(refresh: bool = False, status: dict | None = None) -> dict:
    settings = get_settings()
    strong, fast = effective_models()
    catalogue = model_catalogue(refresh)
    known = {m for entry in catalogue for m in entry["models"]}
    return {
        "catalogue": catalogue,
        "providers": {p.key: {"label": p.label, "key_env": p.key_env, "key_url": p.key_url,
                              "masked": mask_key(os.getenv(p.key_env, "")), "has_key": bool(os.getenv(p.key_env, "").strip())}
                      for p in PROVIDERS.values()},
        "strong": strong, "fast": fast,
        "strong_custom": strong not in known, "fast_custom": fast not in known,
        "defaults": (settings.llm_model, settings.llm_fast_model),
        "is_default": (strong, fast) == (settings.llm_model, settings.llm_fast_model),
        "missing_keys": missing_keys_for((strong, fast)),
        "ai_answers": services.ai_answers_wanted(),
        "model_status": status or {},
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, refresh: int = 0):
    settings = get_settings()
    history = get_history()
    return render(
        request, "settings.html", page="settings",
        settings=settings, show_technical=_show_technical(),
        counts={"documents": len(services.list_documents()), "conversations": len(history.conversations(1000))},
        recent_errors=_recent_errors(), **_models_context(refresh=bool(refresh)),
    )


def _valid_model(value: str) -> str:
    value = " ".join((value or "").split())
    provider, name = split_model(value)
    if provider not in PROVIDERS or not name or any(ch in name for ch in " /\\"):
        raise UserInputError("Choose a model from the list, or enter one as provider:model "
                             "(for example google_genai:gemini-3.8-flash).")
    return value


@router.post("/settings/models", response_class=HTMLResponse)
def save_models(request: Request, strong: str = Form(""), fast: str = Form(""),
                strong_custom: str = Form(""), fast_custom: str = Form("")):
    strong = strong_custom if strong == "__custom__" else strong
    fast = fast_custom if fast == "__custom__" else fast
    history = get_history()
    history.set_pref(STRONG_PREF, _valid_model(strong))
    history.set_pref(FAST_PREF, _valid_model(fast))
    audit("models_changed", strong=strong, fast=fast)
    return render(request, "partials/model_settings.html", **_models_context(status={"saved": True}))


@router.post("/settings/models/reset", response_class=HTMLResponse)
def reset_models(request: Request):
    history = get_history()
    history.set_pref(STRONG_PREF, "")
    history.set_pref(FAST_PREF, "")
    return render(request, "partials/model_settings.html", **_models_context(status={"saved": True}))


@router.post("/settings/models/test", response_class=HTMLResponse)
async def test_models(request: Request):
    strong, fast = effective_models()
    results = {}
    for role, model in (("strong", strong), ("fast", fast)):
        started = time.perf_counter()
        try:
            if missing := missing_keys_for((model,)):
                raise UserInputError(f"needs {', '.join(missing)}")
            reply = await run_in_threadpool(lambda m=model: build_chat_model(m, 0.0).invoke("Reply with the single word: ready"))
            results[role] = {"ok": True, "detail": f"replied in {time.perf_counter() - started:.1f} s"}
        except Exception as exc:  # noqa: BLE001 - shown to the user as the test result
            error = classify_exception(exc)
            results[role] = {"ok": False, "detail": error.user_message if not isinstance(exc, UserInputError) else str(exc),
                             "cause": (error.detail or "")[:160]}
    return render(request, "partials/model_settings.html", **_models_context(status={"tests": results}))


@router.post("/settings/keys", response_class=HTMLResponse)
def save_key(request: Request, provider: str = Form(...), api_key: str = Form("")):
    if provider not in PROVIDERS:
        raise UserInputError("Unknown provider.")
    env_var = PROVIDERS[provider].key_env
    set_env_value(env_var, api_key.strip())
    reset_model_cache()
    model_catalogue(refresh=True)
    audit("api_key_updated", provider=provider, cleared=not api_key.strip())
    return render(request, "partials/model_settings.html",
                  **_models_context(status={"saved": True, "key_provider": provider}))


@router.post("/settings/ai-answers", response_class=HTMLResponse)
def set_ai_answers(request: Request, ai_answers: str = Form("off")):
    get_history().set_pref(services.AI_ANSWERS_PREF, "true" if ai_answers == "on" else "false")
    return render(request, "partials/model_settings.html", **_models_context(status={"saved": True}))


@router.post("/settings/technical", response_class=HTMLResponse)
def set_technical(show_technical: str = Form("off")):
    get_history().set_pref("show_technical", "true" if show_technical == "on" else "false")
    return HTMLResponse('<span class="saved">Saved</span>')


@router.post("/settings/clear-history", response_class=HTMLResponse)
def clear_history():
    get_history().clear_conversations()
    return HTMLResponse('<span class="saved">Chat history deleted</span>')


@router.post("/settings/clear-uploads", response_class=HTMLResponse)
def clear_uploads():
    get_history().clear_uploads()
    return HTMLResponse('<span class="saved">Upload history deleted</span>')


@router.get("/health", include_in_schema=False)
def health(request: Request):
    if is_htmx(request):
        return HTMLResponse("ok")
    return {"status": "ok"}
