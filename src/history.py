"""Local app state in SQLite (data/app.db): chat history, upload history,
document catalogue and user preferences.

The app is single-user and local, so there is no per-user separation.
data/app.db is git-ignored and excluded from the submission zip.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, created_at TEXT NOT NULL, meta TEXT
);
CREATE TABLE IF NOT EXISTS upload_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL, outcome TEXT NOT NULL, reason TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    source TEXT PRIMARY KEY, file_type TEXT, topics TEXT, chunks INTEGER, tables TEXT,
    warnings TEXT, added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class Conversation:
    id: str
    title: str
    updated_at: datetime
    message_count: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(messages)")}
            if "meta" not in columns:  # databases created before answer metadata existed
                con.execute("ALTER TABLE messages ADD COLUMN meta TEXT")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    # ---- conversations -------------------------------------------------
    def create_conversation(self, title: str) -> str:
        conversation_id = uuid.uuid4().hex
        title = " ".join(title.split())
        title = title if len(title) <= 60 else title[:57].rstrip() + "..."
        with closing(self._connect()) as con, con:
            con.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (conversation_id, title, _now(), _now()))
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with closing(self._connect()) as con:
            return con.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is not None

    def add_message(self, conversation_id: str, role: str, content: str, sources: list[dict] | None = None,
                    meta: dict | None = None) -> None:
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO messages (conversation_id, role, content, sources, created_at, meta) VALUES (?, ?, ?, ?, ?, ?)",
                # default=str: table excerpts from the Data Analyst can contain date/Decimal values
                (conversation_id, role, content, json.dumps(sources, default=str) if sources else None, _now(),
                 json.dumps(meta, default=str) if meta else None),
            )
            con.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))

    def messages(self, conversation_id: str) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT role, content, sources, meta FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [
            {"role": r["role"], "content": r["content"], "sources": json.loads(r["sources"]) if r["sources"] else [],
             "meta": json.loads(r["meta"]) if r["meta"] else {}}
            for r in rows
        ]

    def conversations(self, limit: int = 50) -> list[Conversation]:
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT c.id, c.title, c.updated_at, COUNT(m.id) AS n
                   FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                   GROUP BY c.id ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Conversation(r["id"], r["title"], datetime.fromisoformat(r["updated_at"]), r["n"]) for r in rows]

    def delete_conversation(self, conversation_id: str) -> None:
        with closing(self._connect()) as con, con:
            con.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def clear_conversations(self) -> None:
        with closing(self._connect()) as con, con:
            con.execute("DELETE FROM conversations")

    # ---- upload history ------------------------------------------------
    def log_upload(self, filename: str, outcome: str, reason: str, details: dict | None = None) -> None:
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO upload_events (filename, outcome, reason, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (filename, outcome, reason, json.dumps(details) if details else None, _now()),
            )

    def uploads(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT filename, outcome, reason, created_at FROM upload_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) | {"created_at": datetime.fromisoformat(r["created_at"])} for r in rows]

    def clear_uploads(self) -> None:
        with closing(self._connect()) as con, con:
            con.execute("DELETE FROM upload_events")

    # ---- document catalogue (friendly metadata shown on the Documents page) ----
    def record_document(self, source: str, file_type: str, topics: list[str], chunks: int,
                        tables: list[str], warnings: list[str]) -> None:
        with closing(self._connect()) as con, con:
            con.execute(
                """INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET file_type = excluded.file_type, topics = excluded.topics,
                   chunks = excluded.chunks, tables = excluded.tables, warnings = excluded.warnings,
                   added_at = excluded.added_at""",
                (source, file_type, json.dumps(topics), chunks, json.dumps(tables), json.dumps(warnings), _now()),
            )

    def documents(self) -> dict[str, dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM documents").fetchall()
        return {
            r["source"]: {
                "file_type": r["file_type"], "topics": json.loads(r["topics"] or "[]"), "chunks": r["chunks"],
                "tables": json.loads(r["tables"] or "[]"), "warnings": json.loads(r["warnings"] or "[]"),
                "added_at": datetime.fromisoformat(r["added_at"]),
            }
            for r in rows
        }

    def forget_document(self, source: str) -> None:
        with closing(self._connect()) as con, con:
            con.execute("DELETE FROM documents WHERE source = ?", (source,))

    # ---- preferences ---------------------------------------------------
    def get_pref(self, key: str, default: str | None = None) -> str | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_pref(self, key: str, value: str) -> None:
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO preferences VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def get_history() -> HistoryStore:
    return HistoryStore(get_settings().history_db)
