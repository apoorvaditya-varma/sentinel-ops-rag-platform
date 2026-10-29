"""Model registry, .env writer, and the Settings-page model/key endpoints."""

import os
from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage

from src import env_file, llm, model_registry
from src.config import get_settings
from src.history import HistoryStore
from src.model_registry import PROVIDERS, available_models, mask_key, split_model
from src.web import pages, services
from tests.fakes import ScriptedChatModel


# ---- registry -----------------------------------------------------------------
def test_split_and_mask():
    assert split_model("google_genai:gemini-3.8-flash") == ("google_genai", "gemini-3.8-flash")
    assert split_model("no-provider") == ("", "no-provider")
    assert mask_key("AQ.abcdefgh1234") == "••••1234" and mask_key("") == ""


def test_without_key_the_built_in_list_is_used(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    models, source = available_models(PROVIDERS["openai"])
    assert source == "built-in" and "gpt-5.5" in models


def test_live_list_is_filtered_sorted_and_cached(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    model_registry._cache.clear()
    payload = {"models": [
        {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.8-flash-tts", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-embedding-2-preview", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-3.1-pro-preview", "supportedGenerationMethods": ["generateContent"]},
    ]}
    calls = []
    monkeypatch.setattr(model_registry, "_get_json", lambda url, headers: calls.append(url) or payload)
    models, source = available_models(PROVIDERS["google_genai"])
    assert source == "live" and models == ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]
    assert available_models(PROVIDERS["google_genai"])[1] == "cached" and len(calls) == 1


def test_network_failure_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    model_registry._cache.clear()

    def boom(url, headers):
        raise TimeoutError("timed out")

    monkeypatch.setattr(model_registry, "_get_json", boom)
    models, source = available_models(PROVIDERS["anthropic"])
    assert source == "built-in" and models[0] == "claude-opus-5-5"


# ---- .env writer --------------------------------------------------------------
def test_env_file_update_preserves_other_lines(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# comment\nAPP_NAME=\"X\"\nGOOGLE_API_KEY=old\nLOG_LEVEL=INFO\n")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_file.set_env_value("GOOGLE_API_KEY", "new-key", path)
    env_file.set_env_value("OPENAI_API_KEY", "sk-test", path)
    text = path.read_text()
    assert text == '# comment\nAPP_NAME="X"\nGOOGLE_API_KEY=new-key\nLOG_LEVEL=INFO\nOPENAI_API_KEY=sk-test\n'
    assert os.environ["OPENAI_API_KEY"] == "sk-test"
    env_file.set_env_value("OPENAI_API_KEY", "", path)
    assert "OPENAI_API_KEY" not in os.environ and "OPENAI_API_KEY=\n" in path.read_text()
    with pytest.raises(ValueError):
        env_file.set_env_value("bad name", "x", path)


# ---- effective models + settings endpoints -------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.web import main

    history = HistoryStore(tmp_path / "app.db")
    for module in (services, pages):
        monkeypatch.setattr(module, "get_history", lambda: history)
    monkeypatch.setattr("src.history.get_history", lambda: history)

    class StubStore:  # the Settings page counts documents; never touch the real index here
        def sources(self):
            return {}

    monkeypatch.setattr(services, "get_store", lambda: StubStore())
    monkeypatch.setattr(pages, "set_env_value", lambda key, value: env_file.set_env_value(key, value, tmp_path / ".env"))
    monkeypatch.setattr(model_registry, "_get_json", lambda url, headers: (_ for _ in ()).throw(TimeoutError()))
    model_registry._cache.clear()
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(main.app) as c:
        yield c, history


def test_defaults_come_from_env_then_preferences_override(client):
    c, history = client
    assert llm.effective_models() == (get_settings().llm_model, get_settings().llm_fast_model)
    r = c.post("/settings/models", data={"strong": "anthropic:claude-opus-5-5", "fast": "google_genai:gemini-3.5-flash-lite"})
    assert r.status_code == 200 and "Saved" in r.text
    assert llm.effective_models() == ("anthropic:claude-opus-5-5", "google_genai:gemini-3.5-flash-lite")
    assert "ANTHROPIC_API_KEY" in r.text and "need" in r.text.lower()  # warns about the missing key
    assert services.ai_enabled() is False
    c.post("/settings/models/reset")
    assert llm.effective_models() == (get_settings().llm_model, get_settings().llm_fast_model)


def test_custom_model_and_validation(client):
    c, _ = client
    r = c.post("/settings/models", data={"strong": "__custom__", "strong_custom": "openai:gpt-5.5", "fast": "google_genai:gemini-3.5-flash-lite"})
    assert r.status_code == 200 and llm.effective_models()[0] == "openai:gpt-5.5"
    r = c.post("/settings/models", data={"strong": "mystery:thing", "fast": "google_genai:gemini-3.5-flash-lite"}, headers={"HX-Request": "true"})
    assert "provider:model" in r.text and r.headers.get("HX-Retarget") == "#flash"


def test_ai_answers_switch_controls_mode(client):
    c, _ = client
    assert services.ai_enabled() is True
    r = c.post("/settings/ai-answers", data={"ai_answers": "off"})
    assert "Off." in r.text and services.ai_enabled() is False
    c.post("/settings/ai-answers", data={"ai_answers": "on"})
    assert services.ai_enabled() is True


def test_save_key_writes_env_masks_and_refreshes(client, tmp_path):
    c, _ = client
    r = c.post("/settings/keys", data={"provider": "openai", "api_key": "sk-test-abcdef1234"})
    assert r.status_code == 200 and "••••1234" in r.text and os.environ["OPENAI_API_KEY"] == "sk-test-abcdef1234"
    assert "OPENAI_API_KEY=sk-test-abcdef1234" in (tmp_path / ".env").read_text()
    assert "sk-test-abcdef1234" not in r.text.replace("••••1234", "")  # never echoed in full
    r = c.post("/settings/keys", data={"provider": "nope", "api_key": "x"})
    assert r.status_code == 400


def test_model_test_endpoint_reports_each_model(client, monkeypatch):
    c, _ = client

    def fake_build(model, temperature):
        if "lite" in model:
            return ScriptedChatModel(responder=lambda m, t: AIMessage(content="ready"))
        return ScriptedChatModel(responder=lambda m, t: (_ for _ in ()).throw(ValueError("API key not valid")))

    monkeypatch.setattr(pages, "build_chat_model", fake_build)
    r = c.post("/settings/models/test")
    assert "✓ google_genai:gemini-3.5-flash-lite — replied in" in r.text
    assert "✗ google_genai:gemini-3.8-flash — The AI service rejected the API key." in r.text


def test_settings_page_shows_catalogue_and_tooltips(client):
    c, _ = client
    html = c.get("/settings").text
    assert "Answer model" in html and "Fast model" in html and 'data-tip="' in html
    assert "Google Gemini: 5 models (built-in)" in html and "Custom…" in html
    assert html.count("data-font-choice") == 3 and html.count("data-theme-choice") == 3
    assert html.count("data-size-choice") == 3
