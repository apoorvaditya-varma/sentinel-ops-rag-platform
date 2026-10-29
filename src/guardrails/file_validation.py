"""Upload guardrail 1: is this a file type we accept, and is it really that type?

Checks run on the raw bytes before anything touches disk outside the staging
area: filename sanitising, extension allow-list, size, and content sniffing
(magic bytes, macro/zip-bomb detection, encoding, parseability).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

import pandas as pd
import yaml
from pypdf import PdfReader

from src.config import get_settings


@dataclass(frozen=True)
class FileType:
    category: str  # document | tabular | structured | log
    examples: str


ALLOWED_TYPES: dict[str, FileType] = {
    ".pdf": FileType("document", "Security policies, standards, audit reports, vendor advisories"),
    ".docx": FileType("document", "Runbooks, SOPs, design docs, postmortems"),
    ".md": FileType("document", "Wiki pages, playbooks, READMEs"),
    ".txt": FileType("document", "Runbooks, notes, plain-text exports"),
    ".csv": FileType("tabular", "SIEM alerts, scan results, asset inventories, deploy logs"),
    ".xlsx": FileType("tabular", "Vulnerability scans, risk registers, compliance trackers"),
    ".json": FileType("structured", "Cloud configs, IAM policies, SIEM/scanner exports (JSON or JSON Lines)"),
    ".yaml": FileType("structured", "Kubernetes manifests, CI/CD pipelines, Ansible playbooks"),
    ".yml": FileType("structured", "Kubernetes manifests, CI/CD pipelines, Ansible playbooks"),
    ".log": FileType("log", "Application, audit and system logs"),
}

_BLOCKED_GROUPS: dict[str, tuple[str, ...]] = {
    "Legacy Word format is not supported - save it as .docx or PDF.": (".doc", ".rtf", ".odt"),
    "Legacy Excel format is not supported - save it as .xlsx or CSV.": (".xls", ".ods"),
    "Macro-enabled Office files are blocked for security.": (".docm", ".xlsm", ".pptm", ".dotm", ".xltm"),
    "Executables and scripts are blocked for security.": (
        ".exe", ".dll", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js",
        ".jar", ".sh", ".py", ".app", ".dmg", ".pkg", ".deb", ".rpm", ".iso", ".bin",
    ),
    "Archives are blocked - upload the individual documents instead.": (
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ),
    "Images and scanned documents are not supported (no OCR) - upload a text-based PDF.": (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic",
    ),
}
BLOCKED_TYPES: dict[str, str] = {ext: reason for reason, exts in _BLOCKED_GROUPS.items() for ext in exts}
_EXECUTABLE_EXTENSIONS = set(_BLOCKED_GROUPS["Executables and scripts are blocked for security."])

_TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"}
_OOXML_MARKERS = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml"}
_MAX_UNZIPPED_BYTES = 250 * 1024 * 1024
_MAX_ZIP_RATIO = 100


class FileRejected(ValueError):
    """Raised with a user-facing reason when an upload fails validation."""


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    extension: str
    category: str
    size_bytes: int
    sha256: str


def safe_filename(name: str) -> str:
    """Strip paths, control characters and exotic symbols; cap the length."""
    base = unicodedata.normalize("NFKC", name.replace("\\", "/")).split("/")[-1].strip()
    if base.startswith("."):
        raise FileRejected("Hidden files (names starting with '.') are not accepted.")
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    stem, dot, ext = base.rpartition(".")
    if dot and len(base) > 120:
        base = f"{stem[: 119 - len(ext)]}.{ext}"
    if not base:
        raise FileRejected("File name is empty.")
    return base


def validate_upload(name: str, data: bytes) -> ValidatedFile:
    """Validate an upload end to end; raise FileRejected with a reason on failure."""
    filename = safe_filename(name)
    suffixes = [s.lower() for s in PurePosixPath(filename).suffixes]
    ext = suffixes[-1] if suffixes else ""

    if ext in BLOCKED_TYPES:
        raise FileRejected(BLOCKED_TYPES[ext])
    if ext not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        raise FileRejected(f"'{ext or 'no extension'}' files are not accepted. Allowed: {allowed}.")
    if any(s in _EXECUTABLE_EXTENSIONS for s in suffixes[:-1]):
        raise FileRejected("Suspicious double extension (e.g. report.exe.pdf).")

    size = len(data)
    limit_mb = get_settings().max_upload_mb
    if size == 0:
        raise FileRejected("File is empty.")
    if size > limit_mb * 1024 * 1024:
        raise FileRejected(f"File is {size / 1024 / 1024:.1f} MB; the limit is {limit_mb} MB.")

    if ext == ".pdf":
        _check_pdf(data)
    elif ext in _OOXML_MARKERS:
        _check_ooxml(data, ext)
    else:
        _check_text(decode_text(data), ext)

    return ValidatedFile(filename, ext, ALLOWED_TYPES[ext].category, size, hashlib.sha256(data).hexdigest())


def decode_text(data: bytes) -> str:
    """Decode a text upload, rejecting binary content disguised as text."""
    if b"\x00" in data[:8192]:
        raise FileRejected("File contains binary data, not text.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileRejected("File is not valid UTF-8 or Windows-1252 text.")
    sample = text[:8192]
    control = sum(1 for ch in sample if unicodedata.category(ch) == "Cc" and ch not in "\r\n\t\f")
    if sample and control / len(sample) > 0.01:
        raise FileRejected("File contains binary data, not text.")
    return text


def read_csv_text(text: str, nrows: int | None = None) -> pd.DataFrame:
    """Parse CSV text, sniffing only real delimiters (comma, semicolon, tab, pipe)."""
    try:
        delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    return pd.read_csv(io.StringIO(text), sep=delimiter, nrows=nrows)


def _check_pdf(data: bytes) -> None:
    if b"%PDF-" not in data[:1024]:
        raise FileRejected("File has a .pdf extension but is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise FileRejected("PDF is password-protected.")
        pages = len(reader.pages)
        if pages > get_settings().max_pdf_pages:
            raise FileRejected(f"PDF has {pages} pages; the limit is {get_settings().max_pdf_pages}.")
        sample = "".join((page.extract_text() or "") for page in reader.pages[:5])
    except FileRejected:
        raise
    except Exception as exc:
        raise FileRejected(f"PDF could not be read ({exc.__class__.__name__}).") from exc
    if len(sample.strip()) < 20:
        raise FileRejected("PDF has no extractable text (scanned image?). OCR is not supported.")


def _check_ooxml(data: bytes, ext: str) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise FileRejected(f"File has a {ext} extension but is not an Office document.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise FileRejected(f"{ext} file is corrupt.") from exc
    names = {info.filename for info in infos}
    if _OOXML_MARKERS[ext] not in names:
        raise FileRejected(f"File has a {ext} extension but its contents do not match.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise FileRejected("Document contains macros, which are blocked for security.")
    unzipped = sum(info.file_size for info in infos)
    if unzipped > _MAX_UNZIPPED_BYTES or unzipped > len(data) * _MAX_ZIP_RATIO:
        raise FileRejected("Document expands to an unsafe size (possible zip bomb).")


def _check_text(text: str, ext: str) -> None:
    if not text.strip():
        raise FileRejected("File has no text content.")
    if ext == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            lines = [line for line in text.splitlines() if line.strip()]
            try:
                for line in lines:
                    json.loads(line)
            except json.JSONDecodeError as exc:
                raise FileRejected(f"Invalid JSON / JSON Lines: {exc.msg} (line {exc.lineno}).") from exc
    elif ext in (".yaml", ".yml"):
        try:
            list(yaml.safe_load_all(text))
        except yaml.YAMLError as exc:
            raise FileRejected(f"Invalid YAML: {str(exc).splitlines()[0]}") from exc
    elif ext == ".csv":
        try:
            frame = read_csv_text(text, nrows=50)
        except Exception as exc:
            raise FileRejected(f"CSV could not be parsed ({exc.__class__.__name__}).") from exc
        if frame.empty or len(frame.columns) < 2:
            raise FileRejected("CSV needs a header row, at least two columns and one data row.")
