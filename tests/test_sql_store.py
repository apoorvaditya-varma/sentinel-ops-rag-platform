import pandas as pd
import pytest

from src.tables.sql_store import QueryRejected, TableStore


@pytest.fixture
def store(tmp_path):
    store = TableStore(tmp_path / "tables.duckdb")
    store.add_tables("scan.xlsx", {"scan__findings": pd.DataFrame({
        "cve id": ["CVE-2024-6387", "CVE-2021-44228", "CVE-2024-3094"],
        "severity": ["High", "Critical", "Critical"],
        "status": ["Open", "Open", "Fixed"],
    })})
    yield store
    store.close()


def test_tables_registered_with_clean_names(store):
    assert store.tables() == {"scan__findings": "scan.xlsx"}
    assert "cve_id (VARCHAR)" in store.describe("scan__findings")


def test_select_works(store):
    result = store.run_query("SELECT severity, COUNT(*) AS n FROM scan__findings GROUP BY 1 ORDER BY 1")
    assert result.columns == ["severity", "n"]
    assert result.rows == [("Critical", 2), ("High", 1)]


def test_results_are_truncated(store):
    result = store.run_query("SELECT * FROM range(1000)", max_rows=10)
    assert len(result.rows) == 10 and result.truncated


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("DROP TABLE scan__findings", "Only SELECT"),
        ("DELETE FROM scan__findings", "Only SELECT"),
        ("SELECT 1; DROP TABLE scan__findings", "exactly one"),
        ("SELECT * FROM _table_sources", "Internal tables"),
        ("SELECT * FROM read_csv('/etc/passwd')", "SQL error"),
        ("SELECT * FROM no_such_table", "SQL error"),
    ],
)
def test_unsafe_or_invalid_sql_rejected(store, sql, reason):
    with pytest.raises(QueryRejected, match=reason):
        store.run_query(sql)
    assert store.run_query("SELECT COUNT(*) FROM scan__findings").rows == [(3,)]


def test_reloading_a_source_replaces_its_tables(store):
    store.add_tables("scan.xlsx", {"scan__findings": pd.DataFrame({"a": [1]})})
    assert store.run_query("SELECT COUNT(*) FROM scan__findings").rows == [(1,)]
    store.delete_source("scan.xlsx")
    assert store.tables() == {}
