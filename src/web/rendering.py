"""Jinja templates and helpers shared by the page routes and error handlers."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src import __version__
from src.config import get_settings
from src.agents.registry import ALL_AGENTS
from src.web import presenters
from src.web.services import ai_enabled


def ask_url() -> str:
    from src.web.pages import last_conversation_url  # late import: pages imports this module

    return last_conversation_url()

WEB_DIR = Path(__file__).parent

@lru_cache(maxsize=64)
def _fingerprint(path: str, mtime: float) -> str:
    return hashlib.sha256((WEB_DIR / "static" / path).read_bytes()).hexdigest()[:10]


def asset(path: str) -> str:
    """'/static/<path>?v=<content hash>' - changes whenever the file changes."""
    file = WEB_DIR / "static" / path
    return f"/static/{path}?v={_fingerprint(path, file.stat().st_mtime)}"


templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.filters["md"] = presenters.render_markdown
templates.env.filters["answer"] = presenters.render_answer
templates.env.filters["agent_title"] = lambda key: ALL_AGENTS[key].title if key in ALL_AGENTS else key
templates.env.filters["local_time"] = presenters.local_time
templates.env.globals.update(
    app_name=get_settings().app_name, version=__version__, ai_enabled=ai_enabled,
    display_name=presenters.display_name, asset=asset, ask_url=ask_url,
)


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
