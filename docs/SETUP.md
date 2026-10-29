# Setup Guide — Sentinel Ops RAG Platform

Step-by-step instructions for the **first-time install** on macOS, Linux or
Windows. No Docker, database server or cloud account is needed; the only
external service is the AI provider (Google Gemini by default; OpenAI and
Anthropic can be chosen in Settings). For day-to-day start/stop, data locations
and troubleshooting after the install, see the [operations handbook](HANDBOOK.md).

**Time needed:** about 10 minutes (most of it is the one-time dependency and model download).

---

## 1. Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Python | **3.11 or 3.12** (3.13+ not yet supported by all ML wheels) | `python3 --version` |
| pip | 23+ | `python3 -m pip --version` |
| Disk space | ~1.5 GB (virtualenv ~1.2 GB + local models ~200 MB) | |
| Internet | Needed for install, first model download and LLM calls | |
| Gemini API key | Free tier is enough | <https://aistudio.google.com/apikey> |

Install Python 3.12 if needed:

- **macOS:** `brew install python@3.12`
- **Ubuntu/Debian:** `sudo apt install python3.12 python3.12-venv`
- **Windows:** install from <https://www.python.org/downloads/> and tick *Add python.exe to PATH*; then use `py -3.12` instead of `python3.12` below.

## 2. Get the code

Unzip the submission (or clone the repository) and open a terminal in the
project folder:

```bash
cd sentinel-ops-rag-platform
```

## 3. Create the virtual environment and install dependencies

macOS / Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> If PowerShell blocks the activate script, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

All later commands assume the virtual environment is **activated** (your prompt shows `(.venv)`).

## 4. Configure environment variables

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

Open `.env` and set your key:

```
GOOGLE_API_KEY=your-key-here
```

Everything else has working defaults. The most useful settings:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL` | `google_genai:gemini-3.8-flash` | Strong model: planning, answers, table analysis |
| `LLM_FAST_MODEL` | `google_genai:gemini-3.5-flash-lite` | Cheap model: supervisor plan, passage grading, reviewer, borderline upload screening |
| `MAX_RETRIEVAL_RETRIES` / `MAX_ANSWER_RETRIES` | `2` / `1` | Researcher query rewrites / reviewer-requested answer revisions |
| `AGENT_RECURSION_LIMIT` / `LLM_TIMEOUT_S` | `25` / `60` | Safety limit on agent steps per question / per-call LLM timeout |
| `EMBEDDING_MODEL` / `SPARSE_MODEL` / `RERANKER_MODEL` | bge-small / BM25 / MiniLM | Local retrieval models (no key needed) |
| `FETCH_K` / `TOP_K` | `20` / `5` | Hybrid-search candidates / chunks kept after reranking |
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `7400` | Where the web app listens. There is no login, so keep it on localhost |
| `MAX_UPLOAD_MB` | `25` | Per-file upload limit |
| `RELEVANCE_ACCEPT_MARGIN` / `RELEVANCE_REJECT_MARGIN` | `0.05` / `0.0` | Topic-screening thresholds (see [ARCHITECTURE.md](ARCHITECTURE.md#upload-screening)) |
| `ALLOW_RELEVANCE_OVERRIDE` | `true` | Offer *Add anyway* for borderline files |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LOG_ROTATION` | `size` | `size` (every `LOG_MAX_MB`, default 10), `time` (every `LOG_ROTATE_WHEN`, default `midnight`), or `off` |
| `LOG_BACKUP_COUNT` | `5` | Rotated files kept per log |
| `LOG_FORMAT` | `text` | `text`, or `json` (one object per line, for log shippers / SIEM) |
| `LOG_DIR` / `LOG_TO_FILE` | `logs` / `true` | Log folder; set `LOG_TO_FILE=false` for console only |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | off | Optional tracing of every agent step |

**Changing models or providers.** The `.env` values are the defaults. On the **Settings** page you can
paste a Google, OpenAI or Anthropic key (it is written to `.env`), pick the *Answer model* and *Fast model*
from the provider's current list (fetched live with your key; a built-in list is used offline), type any
`provider:model` string under *Custom…*, click **Test models** to check both reply, and reset to the
`.env` defaults. Changes apply to the next question without a restart. The three provider packages
(`langchain-google-genai`, `langchain-openai`, `langchain-anthropic`) are installed with the requirements.

## 5. Verify the setup

```bash
python -m scripts.check_setup
```

The first run downloads the local models (~200 MB) into `.cache/`. Expected output:

```
[ OK ] Python version - 3.12.x
[ OK ] Configuration - app='Sentinel Ops RAG Platform', fetch_k=20, top_k=5
[ OK ] Dense embeddings (first run downloads the model) - BAAI/bge-small-en-v1.5, dim=384
[ OK ] Sparse BM25 embeddings - Qdrant/bm25, 4 terms
[ OK ] Cross-encoder reranker - Xenova/ms-marco-MiniLM-L-6-v2
[ OK ] Strong LLM - google_genai:gemini-3.8-flash replied 'ready'
[ OK ] Fast LLM - google_genai:gemini-3.5-flash-lite replied 'ready'

All checks passed.
```

## 6. Start it for the first time

```bash
python -m src.web
```

Open <http://127.0.0.1:7400>, go to **Documents → Try sample documents**, then ask a question on **Ask**.
Stop the app with `Ctrl+C`. Everything from here on (daily start/stop, using the pages, where data
lives, the API, routine tasks and runtime troubleshooting) is in the
[operations handbook](HANDBOOK.md).

## 7. Run the tests (optional)

```bash
python -m pytest -q
```

The 196 tests are offline: the LLM stage is replaced by scripted models and only the local search
models are used. The retrieval tests index the sample corpus into a temporary folder, so your real index
is not touched. The retrieval and answer-quality evaluations are described in the handbook's
[Evaluations](HANDBOOK.md#10-evaluations) section.

## 8. Regenerate sample data and diagrams (optional)

```bash
python -m scripts.generate_sample_data     # data/sample_docs/ (core corpus + extra/, offtopic/, redteam/)
python -m scripts.draw_architecture        # docs/architecture.svg
```

Packaging the submission zip and resetting local data are covered in the handbook
([Packaging](HANDBOOK.md#9-packaging), [Routine tasks](HANDBOOK.md#4-routine-tasks)).

---

## Install troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: No matching distribution found` / build errors during `pip install` | You are on Python 3.13+ or 3.10-. Recreate the venv with Python 3.12. |
| `[SKIP] LLM round-trips - set GOOGLE_API_KEY` | `.env` is missing or the key is empty. The file must be named exactly `.env` in the project root. Keys can also be entered later on the Settings page. |
| `403 PERMISSION_DENIED` / `API key not valid` in `check_setup` | Regenerate the key in Google AI Studio and paste it without quotes or spaces. |
| Model download hangs or fails | Check proxy/firewall access to `huggingface.co`; delete `.cache/fastembed` and rerun `check_setup`. |
| VS Code shows "package not installed" warnings | *Python: Select Interpreter* → `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`). |
| Anything after the app has started | See the handbook's [Troubleshooting](HANDBOOK.md#7-troubleshooting) table. |
