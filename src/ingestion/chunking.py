"""Task 4: split loaded Documents into retrieval-sized chunks.

- Prose (PDF, DOCX, TXT, MD, LOG): recursive splitter that prefers Markdown
  headings, paragraphs, lines, then sentences.
- Structured text (JSON, YAML): splits on YAML document breaks / blank lines.
- Tables: rows are grouped into chunks that fit CHUNK_SIZE and every chunk
  repeats the table name and row range, so a chunk is never a headerless
  fragment.

Every chunk carries a one-line source header (used for embedding and
citations), is secret-redacted, flagged `untrusted` when it contains a
suspected prompt injection, and gets a deterministic id so re-ingesting the
same file is idempotent.
"""

from __future__ import annotations

import hashlib
import uuid

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import get_settings
from src.guardrails.content_scan import redact_secrets, scan_text

_PROSE_SEPARATORS = ["\n# ", "\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]
_STRUCTURED_SEPARATORS = ["\n---\n", "\n\n", "\n", " ", ""]
_ID_NAMESPACE = uuid.UUID("6f1c2d9e-5b7a-4c3e-9a10-2f4b8d7e1c55")


def chunk_documents(docs: list[Document], file_sha256: str) -> list[Document]:
    settings = get_settings()
    prose = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap, separators=_PROSE_SEPARATORS
    )
    structured = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap, separators=_STRUCTURED_SEPARATORS
    )

    pieces: list[tuple[str, dict]] = []
    for doc in docs:
        meta = doc.metadata
        if meta.get("rows") and meta["rows"] != "schema":
            # Each row group cites its own row range, not the loader's 25-row block.
            pieces.extend(
                (text, {**meta, "rows": rows}) for rows, text in _split_table_rows(doc.page_content, settings.chunk_size)
            )
            continue
        if meta.get("file_type") in ("json", "yaml", "yml"):
            texts = structured.split_text(doc.page_content)
        elif meta.get("rows") == "schema":
            texts = [doc.page_content]
        else:
            texts = prose.split_text(doc.page_content)
        pieces.extend((text, meta) for text in texts if text.strip())

    chunks = []
    for index, (text, meta) in enumerate(pieces):
        untrusted = bool(scan_text(text).injection_snippets)
        content = f"{source_header(meta)}\n{redact_secrets(text.strip())}"
        chunk_id = str(uuid.uuid5(_ID_NAMESPACE, f"{file_sha256}:{index}:{hashlib.sha256(content.encode()).hexdigest()}"))
        chunks.append(
            Document(
                page_content=content,
                metadata={**meta, "chunk_id": chunk_id, "chunk_index": index,
                          "file_sha256": file_sha256, "untrusted": untrusted},
            )
        )
    return chunks


def source_header(meta: dict) -> str:
    """e.g. 'Source: information_security_policy.pdf (page 2)'."""
    location = []
    if meta.get("page"):
        location.append(f"page {meta['page']}")
    if meta.get("sheet"):
        location.append(f"sheet {meta['sheet']}")
    return f"Source: {meta['source']}" + (f" ({', '.join(location)})" if location else "")


def _split_table_rows(text: str, chunk_size: int) -> list[tuple[str, str]]:
    """Return [(row_range, chunk_text)]."""
    header, _, body = text.partition("\n")
    table_name = header.split(" rows ")[0]  # "Table 'x'"
    lines = [line for line in body.splitlines() if line.strip()]
    first_row = int(header.split(" rows ")[1].split("-")[0]) if " rows " in header else 1

    groups, current, start = [], [], first_row
    for offset, line in enumerate(lines):
        if current and len("\n".join(current)) + len(line) > chunk_size:
            groups.append((start, start + len(current) - 1, current))
            current, start = [], first_row + offset
        current.append(line)
    if current:
        groups.append((start, start + len(current) - 1, current))
    return [(f"{a}-{b}", f"{table_name} rows {a}-{b}:\n" + "\n".join(rows)) for a, b, rows in groups]
