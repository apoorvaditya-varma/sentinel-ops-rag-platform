"""Application errors with severity levels, user-facing messages and retry hints.

Every failure that reaches the UI is converted to an `AppError` by
`classify_exception`, so users see a plain-language message plus a reference
ID while the full traceback goes to the logs under the same ID.

Severity levels:
    INFO      expected situation the user can act on (e.g. empty knowledge base)
    WARNING   degraded or temporary problem (rate limit, network blip); retrying may work
    ERROR     the action failed (bad API key, unreadable file, storage problem)
    CRITICAL  the app cannot work until an operator fixes something (config, corrupted store)
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def log_level(self) -> int:
        return {"info": logging.INFO, "warning": logging.WARNING,
                "error": logging.ERROR, "critical": logging.CRITICAL}[self.value]


class AppError(Exception):
    code = "UNEXPECTED"
    severity = Severity.ERROR
    transient = False
    user_message = "Something went wrong. Please try again."
    hint = ""

    def __init__(self, user_message: str | None = None, *, hint: str | None = None, detail: str = "") -> None:
        self.user_message = user_message or self.user_message
        self.hint = hint if hint is not None else self.hint
        self.detail = detail
        self.reference = uuid.uuid4().hex[:8]
        super().__init__(f"[{self.code}] {self.user_message}" + (f" ({detail})" if detail else ""))


# ---- configuration -------------------------------------------------------------
class ConfigError(AppError):
    code = "CONFIG"
    severity = Severity.CRITICAL
    user_message = "The application is not configured correctly."
    hint = "Check the .env file against .env.example."


class MissingAPIKeyError(ConfigError):
    code = "MISSING_API_KEY"
    severity = Severity.WARNING
    user_message = "AI features are not enabled yet."
    hint = "Add a Google Gemini API key to the .env file (GOOGLE_API_KEY) and restart the app."


# ---- AI model provider ------------------------------------------------------------
class ModelError(AppError):
    code = "MODEL"
    user_message = "The AI service returned an error."


class ModelAuthError(ModelError):
    code = "MODEL_AUTH"
    user_message = "The AI service rejected the API key."
    hint = "Check GOOGLE_API_KEY in .env, or create a new key in Google AI Studio."


class ModelNotFoundError(ModelError):
    code = "MODEL_NOT_FOUND"
    user_message = "The configured AI model is not available."
    hint = "Update LLM_MODEL / LLM_FAST_MODEL in .env to a current model."


class RateLimitError(ModelError):
    code = "RATE_LIMIT"
    severity = Severity.WARNING
    transient = True
    user_message = "The AI service is busy or the usage limit was reached."
    hint = ("Wait a minute and try again. If this keeps happening, the daily free-tier limit for this model "
            "is probably used up: choose a different Answer model in Settings → Models.")


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    severity = Severity.WARNING
    transient = True
    user_message = "A service could not be reached."
    hint = "Check your internet connection and try again."


# ---- local storage / data ---------------------------------------------------------
class StorageError(AppError):
    code = "STORAGE"
    user_message = "The knowledge base could not be read or updated."


class StoreLockedError(StorageError):
    code = "STORE_LOCKED"
    severity = Severity.CRITICAL
    user_message = "The knowledge base is already open in another program."
    hint = "Close other copies of the app or running ingest scripts, then restart."


class IngestionError(AppError):
    code = "INGESTION"
    user_message = "The document could not be added."


class NotFoundError(AppError):
    code = "NOT_FOUND"
    severity = Severity.WARNING
    user_message = "The requested item no longer exists."


class UserInputError(AppError):
    code = "INVALID_INPUT"
    severity = Severity.INFO
    user_message = "Please check your input."


class CancelledError(AppError):
    code = "CANCELLED"
    severity = Severity.INFO
    user_message = "Stopped."


class InvalidRequestError(UserInputError):
    code = "INVALID_REQUEST"
    user_message = "The request was not valid."


def classify_exception(exc: BaseException) -> AppError:
    """Map any exception to an AppError subclass (best effort, message-based for third-party errors)."""
    if isinstance(exc, AppError):
        return exc
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)

    if "already accessed by another instance" in lowered:
        return StoreLockedError(detail=text)
    if status == 429 or "resource_exhausted" in lowered or "rate limit" in lowered or re.search(r"\b429\b", lowered):
        return RateLimitError(detail=text)
    if status in (401, 403) or "api key not valid" in lowered or "permission_denied" in lowered:
        return ModelAuthError(detail=text)
    if (status == 404 and "model" in lowered) or ("model" in lowered and "not found" in lowered):
        return ModelNotFoundError(detail=text)
    if status in (503, 504) or isinstance(exc, (TimeoutError, ConnectionError)) or any(
        s in lowered for s in ("timed out", "timeout", "deadline", "connection refused", "name resolution",
                               "unavailable", "high demand", "overloaded")
    ) or re.search(r"\b50[34]\b", lowered):
        return ServiceUnavailableError(detail=text)
    if type(exc).__module__.split(".")[0].lstrip("_") in ("duckdb", "qdrant_client", "sqlite3", "portalocker"):
        return StorageError(detail=text)
    if isinstance(exc, FileNotFoundError):
        return NotFoundError(detail=text)
    if isinstance(exc, MemoryError):
        err = AppError("The system ran out of memory.", hint="Try a smaller file or restart the app.", detail=text)
        err.severity = Severity.CRITICAL
        return err
    return AppError(detail=text)


def report(exc: BaseException, action: str, logger: logging.Logger | None = None) -> AppError:
    """Classify and log an exception once, with its reference ID and traceback."""
    error = classify_exception(exc)
    (logger or log).log(
        error.severity.log_level,
        "%s failed [ref=%s code=%s]: %s",
        action, error.reference, error.code, error.detail or exc,
        exc_info=error.severity in (Severity.ERROR, Severity.CRITICAL),
    )
    return error


def retry_transient(attempts: int = 4, base_delay: float = 2.0, max_delay: float = 20.0) -> Callable:
    """Retry a function on transient errors (rate limits, timeouts) with exponential backoff."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - classified below
                    error = classify_exception(exc)
                    if not error.transient or attempt == attempts:
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    log.warning("%s: transient %s (attempt %d/%d), retrying in %.1fs",
                                fn.__name__, error.code, attempt, attempts, delay)
                    time.sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator
