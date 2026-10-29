from src.config import PROJECT_ROOT, get_settings, provider_of
from src.guardrails.file_validation import ALLOWED_TYPES, BLOCKED_TYPES


def test_settings_load_with_defaults():
    settings = get_settings()
    assert settings.chunk_overlap < settings.chunk_size
    assert 0 < settings.top_k <= settings.fetch_k
    assert settings.relevance_reject_margin <= settings.relevance_accept_margin
    assert settings.staging_dir.is_dir()
    assert settings.qdrant_dir.is_dir()


def test_provider_parsed_from_model_string():
    assert provider_of("google_genai:gemini-3.8-flash") == "google_genai"
    assert provider_of("no-provider") == ""


def test_required_formats_supported():
    for ext in (".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".json", ".yaml"):
        assert ext in ALLOWED_TYPES
    assert not set(ALLOWED_TYPES) & set(BLOCKED_TYPES)


def test_sample_docs_present():
    sample_dir = PROJECT_ROOT / "data" / "sample_docs"
    assert any(sample_dir.glob("*.pdf"))
    assert any(sample_dir.glob("*.xlsx"))
