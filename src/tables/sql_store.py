"""DuckDB store for CSV / Excel data, queried by the table-analyst agent.

Safety model for LLM-written SQL (defence in depth):
1. The connection disables external access (no file / network reads, COPY,
   ATTACH, INSTALL) and locks its configuration so SQL cannot re-enable it.
2. `run_query` accepts exactly one SELECT statement (DuckDB's own parser).
3. Results are capped at `max_rows` and queries are interrupted after a timeout.
"""

from __future__ import annotations

import atexit
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from src.config import get_settings
from src.logging_setup import audit

_REGISTRY = "_table_sources"


class QueryRejected(ValueError):
    """Raised with a message the agent can act on (e.g. to fix its SQL)."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool

    def to_markdown(self) -> str:
        if not self.rows:
            return "(no rows)"
        frame = pd.DataFrame(self.rows, columns=self.columns)
        note = "\n\n(result truncated)" if self.truncated else ""
        return frame.to_markdown(index=False) + note


def table_name_for(source: str, sheet_key: str) -> str:
    """'vulnerability_scan_2026Q3.xlsx' + 'vulnerability_scan_2026Q3__findings' -> 'vulnerability_scan_2026q3__findings'."""
    name = re.sub(r"[^a-z0-9_]", "_", sheet_key.lower()).strip("_")
    return f"t_{name}" if not name or name[0].isdigit() else name


class TableStore:
    def __init__(self, path: Path) -> None:
        self._con = duckdb.connect(
            str(path), config={"enable_external_access": False, "lock_configuration": True}
        )
        self._lock = threading.Lock()
        self._con.execute(f"CREATE TABLE IF NOT EXISTS {_REGISTRY} (source VARCHAR, table_name VARCHAR)")

    def close(self) -> None:
        self._con.close()

    def add_tables(self, source: str, frames: dict[str, pd.DataFrame]) -> list[str]:
        """Replace all tables previously loaded from `source`; returns the table names."""
        self.delete_source(source)
        names = []
        with self._lock:
            for key, frame in frames.items():
                name = table_name_for(source, key)
                clean = frame.copy()
                clean.columns = _unique_columns(clean.columns)
                self._con.register("_incoming", clean)
                self._con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _incoming')
                self._con.unregister("_incoming")
                self._con.execute(f"INSERT INTO {_REGISTRY} VALUES (?, ?)", [source, name])
                names.append(name)
        return names

    def delete_source(self, source: str) -> None:
        with self._lock:
            rows = self._con.execute(f"SELECT table_name FROM {_REGISTRY} WHERE source = ?", [source]).fetchall()
            for (name,) in rows:
                self._con.execute(f'DROP TABLE IF EXISTS "{name}"')
            self._con.execute(f"DELETE FROM {_REGISTRY} WHERE source = ?", [source])

    def tables(self, sources: list[str] | None = None) -> dict[str, str]:
        """{table_name: source}"""
        cur = self._con.cursor()
        rows = cur.execute(f"SELECT table_name, source FROM {_REGISTRY} ORDER BY table_name").fetchall()
        return {name: src for name, src in rows if not sources or src in sources}

    def describe(self, table: str, sample_rows: int = 3) -> str:
        """Schema + row count + sample rows, formatted for an LLM prompt."""
        if table not in self.tables():
            raise QueryRejected(f"Unknown table '{table}'. Available: {', '.join(self.tables()) or 'none'}")
        cur = self._con.cursor()
        columns = cur.execute(f'DESCRIBE "{table}"').fetchall()
        count = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        sample = cur.execute(f'SELECT * FROM "{table}" LIMIT {sample_rows}').df()
        schema = "\n".join(f"- {name} ({dtype})" for name, dtype, *_ in columns)
        return f"Table {table} ({count} rows)\nColumns:\n{schema}\nSample rows:\n{sample.to_markdown(index=False)}"

    def run_query(self, sql: str, max_rows: int = 200, timeout_s: float = 10.0) -> QueryResult:
        try:
            return self._run_query(sql, max_rows, timeout_s)
        except QueryRejected as exc:
            audit("sql_rejected", sql=sql[:500], reason=str(exc)[:300])
            raise

    def _run_query(self, sql: str, max_rows: int, timeout_s: float) -> QueryResult:
        statements = duckdb.extract_statements(sql)
        if len(statements) != 1:
            raise QueryRejected("Provide exactly one SQL statement.")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise QueryRejected(f"Only SELECT queries are allowed (got {statements[0].type.name}).")
        if re.search(rf"\b{_REGISTRY}\b", sql, re.IGNORECASE):
            raise QueryRejected("Internal tables cannot be queried.")

        cur = self._con.cursor()
        timer = threading.Timer(timeout_s, cur.interrupt)
        timer.start()
        try:
            result = cur.execute(sql)
            columns = [d[0] for d in result.description]
            rows = result.fetchmany(max_rows + 1)
        except duckdb.InterruptException as exc:
            raise QueryRejected(f"Query exceeded {timeout_s:.0f}s and was stopped.") from exc
        except duckdb.Error as exc:
            raise QueryRejected(f"SQL error: {exc}") from exc
        finally:
            timer.cancel()
        return QueryResult(columns, rows[:max_rows], len(rows) > max_rows)


def _unique_columns(columns) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for col in columns:
        base = re.sub(r"\s+", "_", str(col).strip()) or "column"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return out


@lru_cache(maxsize=1)
def get_table_store() -> TableStore:
    store = TableStore(get_settings().tables_db)
    atexit.register(store.close)
    return store
