"""Index accepted files: load -> chunk -> hybrid vector store (+ DuckDB for tables).

Only files that passed screening (and were promoted to data/uploads/) are
indexed here.  Re-indexing a file replaces its previous chunks and tables.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import get_settings
from src.guardrails.file_validation import ALLOWED_TYPES
from src.ingestion.chunking import chunk_documents
from src.ingestion.loaders import load_file, load_tables
from src.logging_setup import audit
from src.tables.sql_store import get_table_store
from src.vectorstore.store import get_store

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    source: str
    chunks: int
    tables: list[str]
    untrusted_chunks: int


def ingest_file(path: Path) -> IngestReport:
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    chunks = chunk_documents(load_file(path), sha256)

    store = get_store()
    store.delete_source(path.name)
    store.add(chunks)

    tables: list[str] = []
    if ALLOWED_TYPES[path.suffix.lower()].category == "tabular":
        tables = get_table_store().add_tables(path.name, load_tables(path))

    report = IngestReport(path.name, len(chunks), tables, sum(c.metadata["untrusted"] for c in chunks))
    log.info("Indexed %s: %d chunks, tables=%s", path.name, report.chunks, tables)
    audit("document_indexed", file=path.name, chunks=report.chunks, tables=tables,
          untrusted_chunks=report.untrusted_chunks)
    return report


def remove_file(source: str) -> None:
    """Delete a file from the vector store, DuckDB and data/uploads/."""
    get_store().delete_source(source)
    get_table_store().delete_source(source)
    (get_settings().upload_dir / source).unlink(missing_ok=True)
    audit("document_removed", file=source)


def reindex_uploads() -> list[IngestReport]:
    """Index every accepted file in data/uploads/ (e.g. after deleting data/qdrant)."""
    upload_dir = get_settings().upload_dir
    return [
        ingest_file(path)
        for path in sorted(upload_dir.iterdir())
        if path.is_file() and path.suffix.lower() in ALLOWED_TYPES
    ]
