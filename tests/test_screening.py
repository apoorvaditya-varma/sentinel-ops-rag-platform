"""Relevance + screening tests.  Uses the local embedding model only: the LLM
stage is disabled so tests are free, offline and deterministic."""

from dataclasses import replace

import pytest
from langchain_core.documents import Document

from src.config import get_settings
from src.guardrails import relevance
from src.guardrails.relevance import Verdict, check_relevance
from src.ingestion import screening
from src.ingestion.loaders import load_file

OFF_TOPIC = {
    "recipe": "Classic lasagna recipe. Preheat the oven to 190C. Brown the beef with onions and garlic, "
    "add crushed tomatoes and simmer for 30 minutes. Layer pasta sheets, ricotta and mozzarella. "
    "Bake for 45 minutes and rest 15 minutes before serving.",
    "football": "Manchester United came from behind to beat Leeds 3-2 on Saturday. After conceding twice "
    "before half-time, the home side equalised with a penalty and won it with a late counter-attack.",
    "hr_leave": "Employee Leave Policy. Full-time employees are entitled to 24 days of paid annual leave per "
    "year plus public holidays. Leave requests go to the line manager two weeks in advance through the HR "
    "portal. Sick leave beyond three days requires a medical certificate.",
    "marketing": "Q4 marketing plan: increase brand awareness among small businesses through a social media "
    "campaign, influencer partnerships and two webinars. KPIs are website traffic and lead conversion rate.",
    "profit_and_loss": "Quarterly profit and loss statement: revenue 4.2M USD, cost of goods sold 2.1M, gross "
    "margin 50 percent, operating expenses 1.3M, EBITDA 0.8M. Accounts receivable days increased to 52.",
    "payroll": "Payroll calendar 2026: salaries are paid on the 25th of each month. Overtime must be approved "
    "by the line manager and submitted by the 15th. Payslips are available in the HR self-service portal.",
}

# Close to FinOps / ITSM vocabulary: must never be auto-accepted (rejected or sent to the LLM / review).
NEAR_MISS = {
    "invoice": "Invoice INV-2026-0442. Bill to: Acme Retail Ltd. 40 units office chairs at 120 USD, 10 standing "
    "desks at 450 USD. Subtotal 9300 USD, VAT 20 percent, total due 11160 USD within 30 days.",
    "facilities_helpdesk": "Facilities helpdesk: report broken lights, heating problems or cleaning requests "
    "through the facilities ticket form. Meeting rooms can be booked via the calendar.",
    "travel_expense": "Travel and expense policy: economy class for flights under six hours, hotel limit of "
    "180 USD per night, meals reimbursed up to 60 USD per day with receipts.",
}

ON_TOPIC_EXTRA = {
    "iam_policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], '
    '"Resource": ["arn:aws:s3:::prod-logs/*"], "Condition": {"Bool": {"aws:SecureTransport": "true"}}}]}',
    "acceptable_use": "Acceptable use policy: company laptops must have disk encryption enabled, users must "
    "not install unapproved software, passwords must be at least 14 characters and never shared, and "
    "suspected phishing emails must be reported to the security team.",
    "itsm_change": "Emergency change CHG-9120 raised after the outage. Approved by the ECAB at 02:10. "
    "Implementation steps, verification steps and backout plan attached. Linked problem PRB-311; CI in the CMDB.",
    "ai_governance": "Generative AI usage standard: staff may use approved LLM assistants only; customer data "
    "must not be entered into public chatbots. AI features require red-team testing for prompt injection.",
    "finops": "Cloud spend for September was 182k USD, up 14 percent, driven by untagged GPU instances. Savings "
    "plan coverage dropped to 61 percent. Recommendation: rightsize RDS and buy a compute savings plan.",
    "resilience": "DR exercise summary: the primary database failed over to the secondary region. Achieved RPO "
    "4 minutes and RTO 2 hours against targets of 15 minutes and 4 hours.",
    "netops": "Network change: add ACL entry permitting TCP 5432 from 10.20.4.0/24 to database VLAN 310. "
    "Update the firewall policy, verify with packet capture, roll back by removing the rule.",
}


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(type(settings), "missing_api_keys", lambda self: ["GOOGLE_API_KEY"])


@pytest.mark.parametrize(
    "path",
    [p for p in sorted(get_settings().sample_docs_dir.glob("*.*"))],
    ids=lambda p: p.name,
)
def test_sample_corpus_accepted(path):
    result = check_relevance(load_file(path))
    assert result.verdict is Verdict.ACCEPTED, (result.margin, result.reason)
    assert result.domains


@pytest.mark.parametrize("name", ON_TOPIC_EXTRA)
def test_other_ops_content_accepted(name):
    result = check_relevance([Document(page_content=ON_TOPIC_EXTRA[name])])
    assert result.verdict is Verdict.ACCEPTED, result.margin


@pytest.mark.parametrize("name", OFF_TOPIC)
def test_off_topic_rejected(name):
    result = check_relevance([Document(page_content=OFF_TOPIC[name])])
    assert result.verdict is Verdict.REJECTED, result.margin


@pytest.mark.parametrize("name", NEAR_MISS)
def test_near_miss_never_auto_accepted(name):
    result = check_relevance([Document(page_content=NEAR_MISS[name])])
    assert result.verdict is not Verdict.ACCEPTED, result.margin


@pytest.mark.parametrize(
    "name, domain",
    [("itsm_change", "itsm"), ("ai_governance", "ai_governance"), ("finops", "finops"),
     ("resilience", "resilience"), ("netops", "netops")],
)
def test_domain_tagged(name, domain):
    result = check_relevance([Document(page_content=ON_TOPIC_EXTRA[name])])
    assert result.domains[0] == domain, result.domains


def test_borderline_without_llm_needs_review(monkeypatch):
    strict = replace(get_settings(), relevance_accept_margin=0.99, relevance_reject_margin=-0.99)
    monkeypatch.setattr(relevance, "get_settings", lambda: strict)
    result = check_relevance([Document(page_content=OFF_TOPIC["marketing"])])
    assert result.verdict is Verdict.NEEDS_REVIEW


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    staging = tmp_path / "uploads" / ".staging"
    staging.mkdir(parents=True)
    settings = replace(get_settings(), upload_dir=tmp_path / "uploads", staging_dir=staging)
    monkeypatch.setattr(screening, "get_settings", lambda: settings)
    return settings


def test_screen_and_promote_flow(isolated_dirs):
    data = (get_settings().sample_docs_dir / "runbook_k8s_crashloopbackoff.txt").read_bytes()
    result = screening.screen_upload("runbook.txt", data)
    assert result.verdict is Verdict.ACCEPTED
    assert result.staged_path.exists()
    target = screening.promote(result)
    assert target.parent == isolated_dirs.upload_dir and target.exists()

    again = screening.screen_upload("copy.txt", data)
    assert again.verdict is Verdict.REJECTED and again.stage == "duplicate"


def test_screen_rejects_off_topic_and_cleans_staging(isolated_dirs):
    result = screening.screen_upload("lasagna.txt", OFF_TOPIC["recipe"].encode())
    assert result.verdict is Verdict.REJECTED and result.stage == "relevance"
    assert not any(isolated_dirs.staging_dir.iterdir())


def test_screen_reports_secrets_and_injection(isolated_dirs):
    redteam = get_settings().sample_docs_dir / "redteam" / "vendor_advisory_with_injection.txt"
    result = screening.screen_upload(redteam.name, redteam.read_bytes())
    assert any("prompt-injection" in w for w in result.warnings)


def test_screen_rejects_bad_type_before_parsing(isolated_dirs):
    result = screening.screen_upload("malware.exe", b"MZ")
    assert result.verdict is Verdict.REJECTED and result.stage == "file_type"
