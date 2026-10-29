"""REST API (JSON). Interactive docs at /api/docs.

Errors use one shape everywhere:
    {"error": {"code", "severity", "message", "hint", "retryable", "reference", "request_id"}}
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field

from src.errors import NotFoundError
from src.history import get_history
from src.vectorstore.store import get_store
from src.web import services
from src.web.pages import ask_cancellable, read_uploads

router = APIRouter(prefix="/api", tags=["api"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=services.MAX_QUESTION_CHARS)
    conversation_id: str | None = None
    sources: list[str] = Field(default_factory=list, description="Restrict the search to these files")


@router.get("/health")
def health() -> dict:
    store = get_store()
    return {"status": "ok", "documents": len(store.sources()), "chunks": store.count(),
            "ai_answers": services.ai_enabled()}


@router.get("/documents")
def documents() -> list[dict]:
    return services.list_documents()


@router.post("/documents")
async def add_documents(files: list[UploadFile] = File(default_factory=list)) -> list[dict]:
    return [asdict(o) for o in services.add_files(await read_uploads(files))]


@router.delete("/documents/{source}")
def remove_document(source: str) -> dict:
    services.remove_document(source)
    return {"removed": source}


@router.post("/ask")
async def ask(request: Request, body: AskRequest) -> dict:
    return asdict(await ask_cancellable(request, body.question, body.conversation_id, body.sources))


@router.get("/conversations")
def conversations(limit: int = 50) -> list[dict]:
    return [asdict(c) for c in get_history().conversations(limit)]


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict:
    history = get_history()
    if not history.conversation_exists(conversation_id):
        raise NotFoundError("Conversation not found.")
    return {"id": conversation_id, "messages": history.messages(conversation_id)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    get_history().delete_conversation(conversation_id)
    return {"deleted": conversation_id}


@router.get("/uploads")
def uploads(limit: int = 100) -> list[dict]:
    return get_history().uploads(limit)
