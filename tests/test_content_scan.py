from src.config import get_settings
from src.guardrails.content_scan import redact_secrets, scan_text


def test_detects_and_redacts_aws_example_keys():
    text = (get_settings().sample_docs_dir / "runbook_leaked_credentials.txt").read_text()
    report = scan_text(text)
    assert report.secrets["aws_access_key"] == 1
    assert "aws_secret_key" in report.secrets
    redacted = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[REDACTED_AWS_ACCESS_KEY]" in redacted


def test_detects_private_key_and_connection_string():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\n"
        "DATABASE_URL=postgres://app:S3cretPass@db.internal:5432/prod"
    )
    report = scan_text(text)
    assert {"private_key", "connection_string"} <= set(report.secrets)
    assert "S3cretPass" not in redact_secrets(text)


def test_detects_hidden_prompt_injection():
    text = (get_settings().sample_docs_dir / "redteam" / "vendor_advisory_with_injection.txt").read_text()
    report = scan_text(text)
    assert report.injection_snippets
    assert any("injection" in w for w in report.warnings)


def test_clean_runbook_has_no_findings():
    text = (get_settings().sample_docs_dir / "runbook_k8s_crashloopbackoff.txt").read_text()
    report = scan_text(text)
    assert not report.secrets and not report.injection_snippets
