from src.config import get_settings
from src.ingestion.chunking import chunk_documents
from src.ingestion.loaders import load_file

SAMPLES = get_settings().sample_docs_dir


def chunks_for(name: str):
    return chunk_documents(load_file(SAMPLES / name), file_sha256="0" * 64)


def test_chunks_respect_size_and_carry_source_header():
    limit = get_settings().chunk_size
    for name in ("information_security_policy.pdf", "runbook_k8s_crashloopbackoff.txt", "siem_alerts_2026-10.csv"):
        for chunk in chunks_for(name):
            header, _, body = chunk.page_content.partition("\n")
            assert header.startswith(f"Source: {name}")
            assert len(body) <= limit
            assert {"chunk_id", "chunk_index", "file_sha256", "untrusted"} <= set(chunk.metadata)


def test_pdf_chunks_keep_page_numbers():
    pages = {c.metadata["page"] for c in chunks_for("information_security_policy.pdf")}
    assert pages and all(isinstance(p, int) for p in pages)


def test_table_chunks_repeat_table_name_and_row_range():
    rows = [c for c in chunks_for("vulnerability_scan_2026Q3.xlsx") if c.metadata["rows"] != "schema"]
    assert len(rows) > 1
    for chunk in rows:
        assert f"Table 'vulnerability_scan_2026Q3__findings' rows {chunk.metadata['rows']}:" in chunk.page_content
        assert "cve_id: CVE-" in chunk.page_content


def test_table_schema_chunk_lists_columns():
    schema = [c for c in chunks_for("deployments_2026-10.csv") if c.metadata["rows"] == "schema"]
    assert len(schema) == 1 and "deploy_id" in schema[0].page_content


def test_secrets_are_masked_in_chunks():
    text = "\n".join(c.page_content for c in chunks_for("runbook_leaked_credentials.txt"))
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "[REDACTED_AWS_ACCESS_KEY]" in text


def test_injection_chunk_flagged_untrusted():
    chunks = chunk_documents(load_file(SAMPLES / "redteam" / "vendor_advisory_with_injection.txt"), "1" * 64)
    assert any(c.metadata["untrusted"] for c in chunks)
    assert not any(c.metadata["untrusted"] for c in chunks_for("runbook_k8s_crashloopbackoff.txt"))


def test_chunk_ids_are_deterministic():
    first = [c.metadata["chunk_id"] for c in chunks_for("postmortem_INC-2041_payment_api_outage.txt")]
    second = [c.metadata["chunk_id"] for c in chunks_for("postmortem_INC-2041_payment_api_outage.txt")]
    assert first == second and len(set(first)) == len(first)
