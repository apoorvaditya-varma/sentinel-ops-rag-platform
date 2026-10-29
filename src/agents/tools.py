"""Tools given to the specialist agents.

The SQL tools are created per request so they only see the tables of the
documents in scope, and they record every query for citations and the trace.
"""

from __future__ import annotations

import re

from langchain_core.tools import BaseTool, tool

from src.tables.sql_store import QueryRejected, TableStore

MAX_ROWS_PER_QUERY = 50


def make_sql_tools(store: TableStore, sources: list[str] | None, query_log: list[dict]) -> list[BaseTool]:
    allowed = store.tables(sources)              # {table: source file}
    hidden = set(store.tables()) - set(allowed)  # tables outside the user's scope

    @tool
    def list_tables() -> str:
        """List the data tables you can query and the file each one came from."""
        if not allowed:
            return "No data tables are available."
        return "\n".join(f"- {name} (from {source})" for name, source in allowed.items())

    @tool
    def describe_table(table: str) -> str:
        """Show the columns, types, row count and sample rows of one table."""
        if table not in allowed:
            return f"ERROR: unknown table '{table}'. Call list_tables first."
        return store.describe(table)

    @tool
    def run_sql(sql: str) -> str:
        """Run ONE read-only SELECT query (DuckDB SQL) and return the result as a table."""
        for name in hidden:
            if re.search(rf"\b{re.escape(name)}\b", sql, re.IGNORECASE):
                error = f"Table '{name}' is outside the documents selected for this question."
                query_log.append({"sql": sql, "error": error})
                return f"ERROR: {error}"
        try:
            result = store.run_query(sql, max_rows=MAX_ROWS_PER_QUERY)
        except QueryRejected as exc:
            query_log.append({"sql": sql, "error": str(exc)})
            return f"ERROR: {exc}"
        markdown = result.to_markdown()
        query_log.append({"sql": sql, "columns": result.columns, "rows": [list(r) for r in result.rows],
                          "truncated": result.truncated, "markdown": markdown})
        return markdown

    return [list_tables, describe_table, run_sql]
