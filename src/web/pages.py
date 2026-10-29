"""HTML pages and HTMX partials."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config import get_settings
from src.errors import UserInputError
from src.guardrails.domains import DOMAINS
from src.guardrails.file_validation import ALLOWED_TYPES
from src.history import get_history
from src.web import services
from src.web.rendering import is_htmx, render
from src.web.presenters import file_kind, history_groups

router = APIRouter(include_in_schema=False)

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
        "messages": history.messages(conversation_id) if conversation_id else [],
        "history": history_groups(history.conversations()),
        "documents": services.list_documents(),
        "starters": STARTER_QUESTIONS,
        "show_technical": _show_technical(),
    }


@router.get("/", response_class=HTMLResponse)
def ask_page(request: Request):
    return render(request, "ask.html", page="ask", **_chat_context(None))


@router.get("/c/{conversation_id}", response_class=HTMLResponse)
def conversation_page(request: Request, conversation_id: str):
    if not get_history().conversation_exists(conversation_id):
        return RedirectResponse("/", status_code=303)
    return render(request, "ask.html", page="ask", **_chat_context(conversation_id))


@router.post("/ask", response_class=HTMLResponse)
def ask(request: Request, question: str = Form(""), conversation_id: str = Form(""),
        scope: list[str] = Form(default_factory=list)):
    result = services.ask(question, conversation_id or None, scope)
    response = render(
        request, "partials/exchange.html",
        result=result, history=history_groups(get_history().conversations()),
        conversation_id=result.conversation_id, show_technical=_show_technical(),
    )
    if result.created:
        response.headers["HX-Push-Url"] = f"/c/{result.conversation_id}"
    return response


@router.delete("/c/{conversation_id}", response_class=HTMLResponse)
def delete_conversation(request: Request, conversation_id: str, current: str = ""):
    get_history().delete_conversation(conversation_id)
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


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = get_settings()
    history = get_history()
    return render(
        request, "settings.html", page="settings",
        settings=settings, show_technical=_show_technical(),
        missing_keys=settings.missing_api_keys(),
        counts={"documents": len(services.list_documents()), "conversations": len(history.conversations(1000))},
        recent_errors=_recent_errors(),
    )


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
