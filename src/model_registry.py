"""LLM providers and the models they offer.

Model lists are fetched live from each provider's models endpoint (with the
user's key) and cached for a few minutes, so the dropdowns stay current as
models are released or retired. A short built-in list is the offline fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

CACHE_SECONDS = 600
REQUEST_TIMEOUT = 8


@dataclass(frozen=True)
class Provider:
    key: str            # LangChain init_chat_model prefix
    label: str
    key_env: str
    key_url: str        # where to create a key
    fallback: tuple[str, ...]
    exclude: tuple[str, ...] = field(default=())


PROVIDERS: dict[str, Provider] = {
    "google_genai": Provider(
        "google_genai", "Google Gemini", "GOOGLE_API_KEY", "https://aistudio.google.com/apikey",
        ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"),
        ("tts", "image", "live", "embedding", "audio", "transcribe", "omni", "robotics", "nano", "deep-research", "antigravity"),
    ),
    "openai": Provider(
        "openai", "OpenAI", "OPENAI_API_KEY", "https://platform.openai.com/api-keys",
        ("gpt-5.5", "gpt-5.4-mini"),
        ("realtime", "audio", "tts", "transcribe", "image", "embedding", "moderation", "search", "instruct",
         "dall-e", "whisper", "codex", "computer-use", "sora"),
    ),
    "anthropic": Provider(
        "anthropic", "Anthropic Claude", "ANTHROPIC_API_KEY", "https://platform.claude.com/settings/keys",
        ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
    ),
}

_cache: dict[str, tuple[float, list[str]]] = {}


def split_model(model: str) -> tuple[str, str]:
    """'google_genai:gemini-3.8-flash' -> ('google_genai', 'gemini-3.8-flash')."""
    provider, _, name = model.partition(":")
    return (provider, name) if name else ("", model)


def provider_of(model: str) -> Provider | None:
    return PROVIDERS.get(split_model(model)[0])


def key_for(provider: Provider) -> str:
    return os.getenv(provider.key_env, "").strip()


def _get_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _fetch(provider: Provider, api_key: str) -> list[str]:
    if provider.key == "google_genai":
        data = _get_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=200", {})
        names = [m["name"].removeprefix("models/") for m in data.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        names = [n for n in names if n.startswith("gemini")]
    elif provider.key == "openai":
        data = _get_json("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"})
        names = [m["id"] for m in data.get("data", []) if m["id"].startswith("gpt-")]
    elif provider.key == "anthropic":
        data = _get_json("https://api.anthropic.com/v1/models?limit=100",
                         {"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        names = [m["id"] for m in data.get("data", []) if m["id"].startswith("claude")]
    else:
        names = []
    names = [n for n in names if not any(word in n.lower() for word in provider.exclude)]
    return sorted(set(names), key=_version_key, reverse=True)


def _version_key(name: str):
    """Sort newest first: numeric parts descending, 'preview' after stable."""
    numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", name)]
    return (numbers[:2] + [0, 0])[:2], "preview" not in name, name


def available_models(provider: Provider, refresh: bool = False) -> tuple[list[str], str]:
    """Return (model names, source) where source is 'live', 'cached' or 'built-in'."""
    api_key = key_for(provider)
    if not api_key:
        return list(provider.fallback), "built-in"
    cached = _cache.get(provider.key)
    if cached and not refresh and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1], "cached"
    try:
        names = _fetch(provider, api_key)
        if names:
            _cache[provider.key] = (time.time(), names)
            return names, "live"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError) as exc:
        log.warning("Could not list %s models: %s", provider.label, exc)
    return list(provider.fallback), "built-in"


def model_catalogue(refresh: bool = False) -> list[dict]:
    """Everything the Settings page needs: one entry per provider."""
    catalogue = []
    for provider in PROVIDERS.values():
        models, source = available_models(provider, refresh)
        catalogue.append({
            "key": provider.key, "label": provider.label, "key_env": provider.key_env, "key_url": provider.key_url,
            "has_key": bool(key_for(provider)), "models": [f"{provider.key}:{m}" for m in models], "source": source,
        })
    return catalogue


def mask_key(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) >= 8 else ("••••" if value else "")
