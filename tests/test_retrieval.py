"""Index the sample corpus into a temporary Qdrant + DuckDB and test retrieval."""

import re
from dataclasses import replace

import pytest

from src.config import get_settings, sample_documents
from src.ingestion import pipeline
from src.retrieval import retriever
from src.retrieval.retriever import query_identifiers, retrieve
from src.tables.sql_store import TableStore
from src.vectorstore.store import KnowledgeStore

SAMPLES = get_settings().sample_docs_dir


def norm(text: str) -> str:
    """PDF text breaks lines mid-sentence; compare with collapsed whitespace."""
    return re.sub(r"\s+", " ", text).lower()


@pytest.fixture(scope="module")
def indexed(tmp_path_factory):
    root = tmp_path_factory.mktemp("index")
    store = KnowledgeStore(root / "qdrant", "test")
    tables = TableStore(root / "tables.duckdb")
    settings = replace(get_settings(), upload_dir=root / "uploads")
    settings.upload_dir.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "get_store", lambda: store)
        mp.setattr(pipeline, "get_table_store", lambda: tables)
        mp.setattr(pipeline, "get_settings", lambda: settings)
        mp.setattr(retriever, "get_store", lambda: store)
        reports = {p.name: pipeline.ingest_file(p) for p in sample_documents()}
        yield store, tables, reports
    store.client.close()
    tables.close()


def test_every_sample_file_indexed(indexed):
    store, tables, reports = indexed
    assert set(store.sources()) == {p.name for p in sample_documents()}
    assert store.count() == sum(r.chunks for r in reports.values())
    assert set(tables.tables().values()) == {"deployments_2026-10.csv", "siem_alerts_2026-10.csv",
                                             "vulnerability_scan_2026Q3.xlsx"}


def test_reingest_is_idempotent(indexed):
    store, _, reports = indexed
    before = store.count()
    report = pipeline.ingest_file(SAMPLES / "runbook_k8s_crashloopbackoff.txt")
    assert report.chunks == reports["runbook_k8s_crashloopbackoff.txt"].chunks
    assert store.count() == before


@pytest.mark.parametrize(
    "query, answer",
    [
        ("Can administrators use text message codes for two-factor login?", "not permitted for administrators"),
        ("How do I undo a bad Kubernetes rollout?", "kubectl rollout undo"),
        ("What was the root cause of the payment outage?", "connection pool"),
        ("Which hosts are affected by CVE-2024-3094?", "CVE-2024-3094"),
        ("Details of deployment DEP-1187", "deploy_id: DEP-1187"),
    ],
)
def test_answer_passage_in_top_k(indexed, query, answer):
    chunks = retrieve(query)
    assert len(chunks) == get_settings().top_k
    assert any(norm(answer) in norm(c.document.page_content) for c in chunks)
    scores = [c.rerank_score for c in chunks]
    assert all(s is not None for s in scores)


def test_source_filter(indexed):
    chunks = retrieve("severity levels", sources=["incident_response_plan.pdf"])
    assert chunks and {c.source for c in chunks} == {"incident_response_plan.pdf"}


def test_identifier_pinning_beats_reranker(indexed):
    ip = "203.0.113.61"
    top = retrieve(f"Alerts from source IP {ip}")[0]
    assert ip in top.document.page_content


def test_query_identifiers():
    assert query_identifiers("CVE-2024-6387 on payments-db-07 via T1059.001 in 2.14.0 from 10.1.2.3 INC-2041") == {
        "cve-2024-6387", "payments-db-07", "t1059.001", "2.14.0", "10.1.2.3", "inc-2041",
    }
    assert query_identifiers("How do I roll back a deployment?") == set()


def test_remove_file_deletes_everything(indexed):
    store, tables, _ = indexed
    pipeline.remove_file("deployments_2026-10.csv")
    assert "deployments_2026-10.csv" not in store.sources()
    assert "deployments_2026-10.csv" not in tables.tables().values()
    pipeline.ingest_file(SAMPLES / "deployments_2026-10.csv")
