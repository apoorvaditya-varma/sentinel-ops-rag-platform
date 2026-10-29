import json
import logging
from dataclasses import replace
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

import pytest

from src import logging_setup
from src.config import get_settings
from src.errors import (
    AppError, ConfigError, ModelAuthError, ModelNotFoundError, NotFoundError, RateLimitError,
    ServiceUnavailableError, Severity, StorageError, StoreLockedError, classify_exception, report, retry_transient,
)


class FakeAPIError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("Storage folder /x is already accessed by another instance of Qdrant client"), StoreLockedError),
        (FakeAPIError("429 RESOURCE_EXHAUSTED quota", 429), RateLimitError),
        (FakeAPIError("API key not valid. Please pass a valid API key.", 400), ModelAuthError),
        (FakeAPIError("models/gemini-9 is not found", 404), ModelNotFoundError),
        (TimeoutError("read timed out"), ServiceUnavailableError),
        (FakeAPIError("503 UNAVAILABLE. This model is currently experiencing high demand.", 503), ServiceUnavailableError),
        (FakeAPIError("504 DEADLINE_EXCEEDED", 504), ServiceUnavailableError),
        (ConnectionError("connection refused"), ServiceUnavailableError),
        (FileNotFoundError("gone.pdf"), NotFoundError),
        (ValueError("weird"), AppError),
    ],
)
def test_classification(exc, expected):
    error = classify_exception(exc)
    assert type(error) is expected
    assert error.user_message and error.reference


def test_storage_library_errors_classified():
    import duckdb

    assert isinstance(classify_exception(duckdb.CatalogException("no table")), StorageError)


def test_severity_and_transient_flags():
    assert RateLimitError().severity is Severity.WARNING and RateLimitError().transient
    assert StoreLockedError().severity is Severity.CRITICAL and not StoreLockedError().transient
    assert ConfigError().severity.log_level == logging.CRITICAL


def test_retry_transient_retries_only_transient(monkeypatch):
    monkeypatch.setattr("src.errors.time.sleep", lambda s: None)
    calls = {"n": 0}

    @retry_transient(attempts=3)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timed out")
        return "ok"

    assert flaky() == "ok" and calls["n"] == 3

    @retry_transient(attempts=3)
    def broken():
        calls["n"] += 1
        raise ValueError("not transient")

    calls["n"] = 0
    with pytest.raises(ValueError):
        broken()
    assert calls["n"] == 1


# ---- logging -----------------------------------------------------------------
@pytest.fixture
def log_config(tmp_path, monkeypatch):
    def configure(**overrides):
        settings = replace(get_settings(), log_dir=tmp_path, log_to_file=True, **overrides)
        monkeypatch.setattr(logging_setup, "get_settings", lambda: settings)
        logging_setup.setup_logging(force=True)
        return settings

    yield configure
    root = logging.getLogger()
    for handler in list(root.handlers) + list(logging.getLogger(logging_setup.AUDIT_LOGGER).handlers):
        handler.close()
    root.handlers.clear()
    logging.getLogger(logging_setup.AUDIT_LOGGER).handlers.clear()
    setattr(root, logging_setup._CONFIGURED_FLAG, False)


def _flush():
    for handler in logging.getLogger().handlers + logging.getLogger(logging_setup.AUDIT_LOGGER).handlers:
        handler.flush()


@pytest.mark.parametrize(
    "rotation, handler_type",
    [("size", RotatingFileHandler), ("time", TimedRotatingFileHandler), ("off", logging.FileHandler)],
)
def test_rotation_modes(log_config, rotation, handler_type):
    settings = log_config(log_rotation=rotation, log_max_mb=2, log_backup_count=3, log_rotate_when="H")
    files = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
    assert {type(h) for h in files} == {handler_type}
    if rotation == "size":
        assert all(h.maxBytes == 2 * 1024 * 1024 and h.backupCount == 3 for h in files)
        files[0].doRollover()
        assert (settings.log_dir / "app.log.1").exists()
    if rotation == "time":
        assert all(h.when == "H" and h.backupCount == 3 for h in files)


def test_files_levels_masking_and_audit(log_config):
    settings = log_config(log_rotation="size")
    logging_setup.new_request_id()
    logging.getLogger("demo").info("token=ghp_%s connecting", "a" * 36)
    logging.getLogger("demo").error("disk full")
    logging_setup.audit("upload_rejected", file="x.exe")
    _flush()
    app_log = (settings.log_dir / "app.log").read_text()
    assert "ghp_" not in app_log and "[REDACTED_GITHUB_TOKEN]" in app_log
    assert "disk full" in (settings.log_dir / "errors.log").read_text()
    assert "connecting" not in (settings.log_dir / "errors.log").read_text()
    assert 'upload_rejected file="x.exe"' in (settings.log_dir / "audit.log").read_text()


def test_json_format_and_request_id(log_config):
    settings = log_config(log_format="json")
    request_id = logging_setup.new_request_id()
    try:
        raise ValueError("bad thing")
    except ValueError as exc:
        error = report(exc, "demo")
    _flush()
    records = [json.loads(line) for line in (settings.log_dir / "errors.log").read_text().splitlines()]
    assert records[-1]["request_id"] == request_id
    assert error.reference in records[-1]["message"] and "ValueError" in records[-1]["exception"]


def test_setup_is_idempotent(log_config):
    log_config()
    count = len(logging.getLogger().handlers)
    logging_setup.setup_logging()
    assert len(logging.getLogger().handlers) == count


def test_invalid_log_config_is_a_config_error(monkeypatch):
    from src import config

    monkeypatch.setenv("LOG_ROTATION", "weekly-ish")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError, match="LOG_ROTATION"):
            config.get_settings()
    finally:
        monkeypatch.delenv("LOG_ROTATION")
        config.get_settings.cache_clear()
