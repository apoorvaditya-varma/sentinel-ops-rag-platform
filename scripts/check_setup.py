"""Environment sanity check: `python -m scripts.check_setup`.

Verifies the Python version, configuration, local embedding model and (if a
key is configured) a round-trip to the LLM.
"""

from __future__ import annotations

import sys

from src.config import get_settings


def check(label: str, fn) -> bool:
    try:
        detail = fn()
        print(f"[ OK ] {label}{f' - {detail}' if detail else ''}")
        return True
    except Exception as exc:  # noqa: BLE001 - report every failure, keep going
        print(f"[FAIL] {label} - {exc}")
        return False


def check_python() -> str:
    if sys.version_info < (3, 11):
        raise RuntimeError(f"Python 3.11+ required, found {sys.version.split()[0]}")
    return sys.version.split()[0]


def check_embeddings() -> str:
    from src.llm import get_embeddings

    vector = get_embeddings().embed_query("kubernetes pod crashloop")
    return f"{get_settings().embedding_model}, dim={len(vector)}"


def check_sparse() -> str:
    from src.llm import get_sparse_embeddings

    vector = get_sparse_embeddings().embed_query("CVE-2024-6387 regreSSHion")
    return f"{get_settings().sparse_model}, {len(vector.indices)} terms"


def check_reranker() -> str:
    from src.llm import get_reranker

    scores = list(get_reranker().rerank("patch deadline", ["Critical CVEs: 7 days.", "Lunch at noon."]))
    if scores[0] <= scores[1]:
        raise RuntimeError(f"unexpected ranking {scores}")
    return get_settings().reranker_model


def check_llm(getter, model: str):
    def run() -> str:
        reply = getter().invoke("Reply with the single word: ready")
        return f"{model} replied '{reply.text.strip()[:40]}'"

    return run


def main() -> int:
    from src.llm import get_chat_model, get_fast_chat_model

    settings = get_settings()
    results = [
        check("Python version", check_python),
        check("Configuration", lambda: f"app='{settings.app_name}', fetch_k={settings.fetch_k}, top_k={settings.top_k}"),
        check("Dense embeddings (first run downloads the model)", check_embeddings),
        check("Sparse BM25 embeddings", check_sparse),
        check("Cross-encoder reranker", check_reranker),
    ]
    from src.config import missing_keys_for
    from src.llm import effective_models

    strong, fast = effective_models()
    if missing := missing_keys_for((strong, fast)):
        print(f"[SKIP] LLM round-trips - set {', '.join(missing)} in .env (or on the Settings page)")
        results.append(False)
    else:
        results.append(check("Strong LLM", check_llm(get_chat_model, strong)))
        results.append(check("Fast LLM", check_llm(get_fast_chat_model, fast)))
    print("\nAll checks passed." if all(results) else "\nSome checks failed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
