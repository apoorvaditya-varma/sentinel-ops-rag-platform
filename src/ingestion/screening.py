"""Upload screening pipeline: the first thing every uploaded file goes through.

    bytes -> file-type validation -> staged to quarantine -> parse -> duplicate check
          -> content scan (secrets, prompt injection) -> domain relevance -> verdict

Only files with an `accepted` verdict (or a reviewed override) leave the
staging area for `data/uploads/`, where ingestion picks them up.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.config import get_settings
from src.guardrails.content_scan import scan_text
from src.guardrails.file_validation import FileRejected, validate_upload
from src.guardrails.relevance import Verdict, check_relevance
from src.ingestion.loaders import load_file
from src.logging_setup import audit

log = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    filename: str
    verdict: Verdict
    stage: str  # file_type | parse | duplicate | relevance
    reason: str
    category: str = ""
    size_bytes: int = 0
    sha256: str = ""
    domains: list[str] = field(default_factory=list)
    relevance_margin: float | None = None
    method: str = ""
    warnings: list[str] = field(default_factory=list)
    secrets_found: int = 0
    injection_passages: int = 0
    staged_path: Path | None = None


def screen_upload(name: str, data: bytes) -> ScreeningResult:
    settings = get_settings()
    try:
        checked = validate_upload(name, data)
    except FileRejected as exc:
        audit("upload_rejected", file=name, stage="file_type", reason=str(exc), size=len(data))
        return ScreeningResult(name, Verdict.REJECTED, "file_type", str(exc))

    duplicate = _find_duplicate(checked.sha256)
    same_name = (settings.upload_dir / checked.filename).exists()
    if duplicate or same_name:
        reason = (f"Identical to already uploaded '{duplicate}'." if duplicate
                  else "A document with this name is already in the knowledge base; remove it first to replace it.")
        audit("upload_rejected", file=checked.filename, stage="duplicate", duplicate_of=duplicate or checked.filename)
        return ScreeningResult(
            checked.filename, Verdict.REJECTED, "duplicate", reason,
            checked.category, checked.size_bytes, checked.sha256,
        )

    staged = settings.staging_dir / f"{checked.sha256[:12]}_{checked.filename}"
    staged.write_bytes(data)
    base = dict(category=checked.category, size_bytes=checked.size_bytes, sha256=checked.sha256)
    try:
        docs = load_file(staged)
    except Exception as exc:  # noqa: BLE001 - any parser failure is a rejection, not a crash
        log.warning("Parsing %s failed: %s", checked.filename, exc)
        staged.unlink(missing_ok=True)
        return ScreeningResult(checked.filename, Verdict.REJECTED, "parse",
                               f"File could not be parsed ({exc.__class__.__name__}).", **base)
    if not docs:
        staged.unlink(missing_ok=True)
        return ScreeningResult(checked.filename, Verdict.REJECTED, "parse", "No readable text found.", **base)

    scan = scan_text("\n".join(doc.page_content for doc in docs))
    relevance = check_relevance(docs)
    result = ScreeningResult(
        checked.filename, relevance.verdict, "relevance", relevance.reason,
        domains=relevance.domains, relevance_margin=round(relevance.margin, 3),
        method=relevance.method, warnings=scan.warnings, secrets_found=sum(scan.secrets.values()),
        injection_passages=len(scan.injection_snippets), staged_path=staged, **base,
    )
    if relevance.verdict is Verdict.REJECTED:
        discard(result)
    if scan.secrets:
        audit("secrets_detected", file=result.filename, kinds=scan.secrets)
    if scan.injection_snippets:
        audit("prompt_injection_flagged", file=result.filename, passages=len(scan.injection_snippets))
    audit(f"upload_{result.verdict.value}", file=result.filename, stage="relevance",
          margin=result.relevance_margin, method=result.method, domains=result.domains)
    return result


def promote(result: ScreeningResult) -> Path:
    """Move a staged file into data/uploads/ (accepted or reviewed files only)."""
    if result.staged_path is None or not result.staged_path.exists():
        raise FileNotFoundError(f"No staged file for {result.filename}")
    target = get_settings().upload_dir / result.filename
    shutil.move(result.staged_path, target)
    result.staged_path = None
    return target


def discard(result: ScreeningResult) -> None:
    if result.staged_path is not None:
        result.staged_path.unlink(missing_ok=True)
        result.staged_path = None


def _find_duplicate(sha256: str) -> str | None:
    for path in get_settings().upload_dir.iterdir():
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
            return path.name
    return None
