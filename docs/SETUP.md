# Setup Guide — Sentinel Ops RAG Platform

Step-by-step instructions to run the platform locally on macOS, Linux or
Windows. No Docker, database server or cloud account is needed; the only
external service is the Google Gemini API.

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

To use a different LLM provider, install its LangChain package and change the
model string, e.g. `pip install langchain-openai` then
`LLM_MODEL=openai:gpt-5.4-mini` and `OPENAI_API_KEY=...`.

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

## 6. Run the application

```bash
python -m src.web
```

Open <http://127.0.0.1:7400>. Stop the app with `Ctrl+C`. Then:

1. Go to **Documents** and click **Try sample documents**, or drag in your own files and click **Add documents**.
   Expand **What can I add?** to see accepted topics and file types.
2. Each file gets a plain-language result:
   - **Added**: indexed immediately; topics and any warnings are shown
   - **Needs your confirmation**: borderline topic; choose *Add anyway* or *Don't add*
   - **Not added**: the reason is shown (wrong type, macros, off-topic, duplicate…)
3. **Your documents** lists everything with friendly names; *Remove* deletes a document everywhere.
   **Details** and **Upload history** are collapsed by default.
4. Go to **Ask** and type a question (Enter sends, Shift+Enter adds a new line), or click a starter question.
   Until AI answers are enabled (Task 7), you see the most relevant passage inline and the other matches under **Sources**.
   Past conversations appear in **History** on the left.
5. **Settings** has the theme (System / Light / Dark), the *Technical details* switch, AI status,
   deleting history, plus collapsed **System details** and **Recent problems**.

The REST API runs on the same server. Interactive docs are at <http://127.0.0.1:7400/api/docs>:

```bash
curl -s localhost:7400/api/health
curl -s -X POST localhost:7400/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "What is the patch SLA for critical vulnerabilities?"}'
curl -s -F files=@my_runbook.docx localhost:7400/api/documents
```

Alternatively, index from the command line (stop the app first, because embedded
Qdrant allows only one process):

```bash
python -m scripts.ingest data/sample_docs          # screen + index a folder
python -m scripts.ingest my_runbook.docx scan.csv  # individual files
python -m scripts.ingest --reindex                 # rebuild the index from data/uploads/
```

Try the guardrails: upload `data/sample_docs/redteam/vendor_advisory_with_injection.txt`
(prompt-injection warning), `runbook_leaked_credentials.txt` (secret-masking
warning), any `.exe`/`.zip`/`.doc` file (blocked type) or a recipe/sports
article (off-topic).

## 7. Run the tests

```bash
python -m pytest -q
```

Tests are offline: the LLM stage is disabled and only the local models are used.
The retrieval tests index the sample corpus into a temporary folder, so your
real index is not touched.

Retrieval benchmark (index the sample corpus first, with the app stopped):

```bash
python -m scripts.ingest data/sample_docs
python -m src.evaluation.retrieval_eval
```

Answer-quality evaluation of the agents (needs `GOOGLE_API_KEY`; about 13 questions × 4–6 LLM calls):

```bash
python -m src.evaluation.answer_eval            # add --limit 3 for a quick check, --no-judge to skip LLM judging
```

Results are printed as a table and saved to `data/eval/results/`.

## 8. Regenerate sample data and diagrams (optional)

```bash
python -m scripts.generate_sample_data     # data/sample_docs/
python -m scripts.draw_architecture        # docs/architecture.svg
```

## 9. Build the submission zip

```bash
bash scripts/make_submission.sh
```

This creates `dist/sentinel-ops-rag-platform-YYYYMMDD.zip`. It excludes `.venv/`,
`.env` (your API key), `.cache/`, indexed data and `__pycache__`. On Windows, run
it from Git Bash or WSL, or zip the folder manually with those exclusions.

## 10. Reset local data

Stop the app, then delete the generated state (it is rebuilt automatically):

```bash
rm -rf data/uploads/* data/qdrant/* data/tables.duckdb* data/app.db logs/
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: No matching distribution found` / build errors during `pip install` | You are on Python 3.13+ or 3.10-. Recreate the venv with Python 3.12. |
| `[SKIP] LLM round-trips - set GOOGLE_API_KEY` | `.env` is missing or the key is empty. The file must be named exactly `.env` in the project root. |
| `403 PERMISSION_DENIED` / `API key not valid` | Regenerate the key in Google AI Studio and paste it without quotes or spaces. |
| `429 RESOURCE_EXHAUSTED` | Free-tier rate limit hit; wait a minute. Uploads only call the LLM for borderline files. |
| `404 model not found` | Model retired or not available to your key. Pick a current ID from <https://ai.google.dev/gemini-api/docs/models> and update `LLM_MODEL` / `LLM_FAST_MODEL`. |
| Model download hangs or fails | Check proxy/firewall access to `huggingface.co`; delete `.cache/fastembed` and rerun `check_setup`. |
| "The knowledge base is already open in another program" (`STORE_LOCKED`) | Embedded Qdrant allows one process. Stop other copies of the app (`pkill -f "src.web"`) before running `scripts.ingest` or `retrieval_eval`. |
| Chat says the knowledge base is empty | Go to **Documents → Try sample documents**, or upload files. After deleting `data/qdrant/`, run `python -m scripts.ingest --reindex`. |
| `address already in use` on start | Another program uses port 7400: set a free port, e.g. `WEB_PORT=7401`, in `.env`. |
| A message shows a reference such as `ref 6dc76e7d` | Search for it in `logs/errors.log` for the full technical details, or open **Settings → Recent problems**. |
| Logs grow too large | Lower `LOG_MAX_MB` / `LOG_BACKUP_COUNT`, switch to `LOG_ROTATION=time`, or raise `LOG_LEVEL` to `WARNING`. |
| VS Code shows "package not installed" warnings | *Python: Select Interpreter* → `.venv/bin/python` (Windows: `.venv\Scripts\python.exe`). |
| Upload rejected as off-topic but it is relevant | Use *Ingest anyway* if offered, or lower `RELEVANCE_REJECT_MARGIN` slightly (e.g. `-0.02`). Adding domain examples in `src/guardrails/domains.py` is the better long-term fix. |
