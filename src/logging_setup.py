"""Logging: console + rotating files, secret masking, request IDs, audit trail.

Files (in LOG_DIR, default logs/):
    app.log     everything at LOG_LEVEL and above
    errors.log  WARNING and above (quick place to look when something breaks)
    audit.log   security-relevant events from the `sentinel.audit` logger
                (rejected uploads, masked secrets, injection flags, blocked SQL, deletions)

Rotation (LOG_ROTATION):
    size  rotate when a file reaches LOG_MAX_MB, keep LOG_BACKUP_COUNT old files
    time  rotate every LOG_ROTATE_WHEN (e.g. midnight, H, D), keep LOG_BACKUP_COUNT
    off   single growing files (not recommended)
LOG_FORMAT=json writes one JSON object per line (for log shippers / SIEM).
"""

from __future__ import annotations

import contextvars
import json
import logging
import uuid
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

from src.config import get_settings
from src.guardrails.content_scan import redact_secrets

AUDIT_LOGGER = "sentinel.audit"
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_CONFIGURED_FLAG = "_sentinel_configured"
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "fastembed", "huggingface_hub", "watchdog", "google_genai")

TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


def new_request_id() -> str:
    """Start a new request scope; every log line until the next call carries this ID."""
    request_id = uuid.uuid4().hex[:8]
    _request_id.set(request_id)
    return request_id


def audit(event: str, **fields) -> None:
    """Write a structured security event to the audit log."""
    details = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in fields.items())
    logging.getLogger(AUDIT_LOGGER).info("%s %s", event, details)


class ContextFilter(logging.Filter):
    """Adds the request ID and masks secrets in every record before it is written."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        message = record.getMessage()
        masked = redact_secrets(message)
        if masked != message:
            record.msg, record.args = masked, None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def _file_handler(path, settings) -> logging.Handler:
    if settings.log_rotation == "size":
        return RotatingFileHandler(
            path, maxBytes=settings.log_max_mb * 1024 * 1024, backupCount=settings.log_backup_count, encoding="utf-8"
        )
    if settings.log_rotation == "time":
        return TimedRotatingFileHandler(
            path, when=settings.log_rotate_when, backupCount=settings.log_backup_count, encoding="utf-8"
        )
    return logging.FileHandler(path, encoding="utf-8")


def setup_logging(force: bool = False) -> None:
    """Configure logging once per process (safe to call repeatedly, e.g. from scripts and the web app)."""
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False) and not force:
        return
    settings = get_settings()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = JsonFormatter() if settings.log_format == "json" else logging.Formatter(TEXT_FORMAT)
    context = ContextFilter()

    console = logging.StreamHandler()
    console.setLevel(settings.log_level)
    console.setFormatter(logging.Formatter(TEXT_FORMAT))
    handlers: list[logging.Handler] = [console]

    audit_logger = logging.getLogger(AUDIT_LOGGER)
    for handler in list(audit_logger.handlers):
        audit_logger.removeHandler(handler)
        handler.close()

    if settings.log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        app_file = _file_handler(settings.log_dir / "app.log", settings)
        app_file.setLevel(settings.log_level)
        error_file = _file_handler(settings.log_dir / "errors.log", settings)
        error_file.setLevel(logging.WARNING)
        handlers += [app_file, error_file]

        audit_file = _file_handler(settings.log_dir / "audit.log", settings)
        audit_file.setFormatter(formatter)
        audit_file.addFilter(context)
        audit_logger.addHandler(audit_file)

    for handler in handlers:
        handler.addFilter(context)
        if handler is not console:
            handler.setFormatter(formatter)
        root.addHandler(handler)

    root.setLevel(min(settings.log_level_no, logging.INFO))  # audit INFO events must pass the root level
    audit_logger.setLevel(logging.INFO)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    setattr(root, _CONFIGURED_FLAG, True)
    logging.getLogger(__name__).debug(
        "Logging configured: level=%s rotation=%s format=%s dir=%s",
        settings.log_level, settings.log_rotation, settings.log_format, settings.log_dir,
    )
