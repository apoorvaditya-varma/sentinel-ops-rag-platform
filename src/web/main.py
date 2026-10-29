"""FastAPI application: server-rendered pages (Jinja + HTMX) and a REST API.

Run with `python -m src.web` (see src/web/__main__.py).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.config import get_settings
from src.errors import (
    AppError, ConfigError, InvalidRequestError, MissingAPIKeyError, ModelAuthError, ModelError, NotFoundError, RateLimitError,
    ServiceUnavailableError, Severity, StoreLockedError, UserInputError, report,
)
from src.guardrails.content_scan import redact_secrets
from src.logging_setup import new_request_id, setup_logging
from src.web import api, pages
from src.web.rendering import WEB_DIR, is_htmx, render

log = logging.getLogger("src.web")

def http_status(error: AppError) -> int:
    for cls, status in (
        (InvalidRequestError, 422), (UserInputError, 400), (NotFoundError, 404), (RateLimitError, 429), (MissingAPIKeyError, 503),
        (ServiceUnavailableError, 503), (StoreLockedError, 503), (ModelAuthError, 502), (ModelError, 502),
        (ConfigError, 500),
    ):
        if isinstance(error, cls):
            return status
    return 500


def error_payload(error: AppError, request: Request) -> dict:
    return {
        "code": error.code,
        "severity": error.severity.value,
        "message": error.user_message,
        "hint": error.hint or None,
        "retryable": error.transient,
        "reference": error.reference,
        "request_id": request.state.request_id,
        # The underlying cause; secrets are masked because this is shown to the user.
        "detail": redact_secrets(error.detail) or None,
        "log_file": "logs/errors.log" if error.severity is not Severity.INFO else "logs/app.log",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings = get_settings()
    log.info("Starting %s v%s on http://%s:%d", settings.app_name, __version__, settings.web_host, settings.web_port)
    yield
    log.info("Shutting down")


app = FastAPI(
    title=f"{get_settings().app_name} API",
    version=__version__,
    description="Upload ops / security documents and ask questions about them.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = new_request_id()
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - unexpected errors become friendly responses, logged once
        response = await _handle(request, exc)
    response.headers["X-Request-ID"] = request.state.request_id
    if not request.url.path.startswith("/static"):
        log.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - started) * 1000)
    return response


async def _handle(request: Request, exc: Exception):
    error = report(exc, f"{request.method} {request.url.path}", log)
    status = http_status(error)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": error_payload(error, request)}, status_code=status)
    context = {"error": error_payload(error, request)}
    if is_htmx(request):
        # Show the message in the page's notification area instead of replacing the target.
        response = render(request, "partials/flash.html", **context)
        response.headers["HX-Retarget"] = "#flash"
        response.headers["HX-Reswap"] = "innerHTML"
        return response
    return render(request, "error.html", status_code=status, **context)


async def _handle_validation(request: Request, exc: RequestValidationError):
    problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    if request.url.path.startswith("/api/"):
        return await _handle(request, InvalidRequestError(detail=problems, hint=problems))
    return await _handle(request, InvalidRequestError(
        "Some information was missing from the form.", hint="Please check it and try again.", detail=problems,
    ))


app.add_exception_handler(AppError, _handle)
app.add_exception_handler(RequestValidationError, _handle_validation)

app.include_router(pages.router)
app.include_router(api.router)
