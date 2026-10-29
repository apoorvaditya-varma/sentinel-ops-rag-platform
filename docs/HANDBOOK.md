# Operations Handbook — Sentinel Ops RAG Platform

How to run the platform on your own computer, day to day. For the first-time
install see [SETUP.md](SETUP.md); for how it works inside see [ARCHITECTURE.md](ARCHITECTURE.md).

Everything runs locally: no Docker, no database server, no cloud account. The only
outbound traffic is to the AI provider you choose (Google Gemini by default), and only
the question plus the retrieved passages are sent.

---

## 0. Received this as a zip? Start here

The submission zip contains the source code, documentation, sample data and the `.env`
configuration file with the project's AI key, so it runs as-is: no virtual environment or index is
included. To run it:

1. Unzip, and open a terminal in the `sentinel-ops-rag-platform` folder.
2. Create the virtual environment and install dependencies ([SETUP.md](SETUP.md) step 3), e.g. on macOS/Linux:
   ```bash
   python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
   ```
3. `python -m scripts.check_setup` to verify, then continue with section 1.

If there is no `.env` file, create one with `cp .env.example .env`
(Windows: `copy .env.example .env`) and add a key either in that file (`GOOGLE_API_KEY=…`, free at
<https://aistudio.google.com/apikey>) or later on the **Settings** page. **Without a key the app still
runs**: uploads, screening, search and the chat all work, and the chat shows the most relevant passages
instead of AI-written answers.

The included key is on Google's free tier, which allows a limited number of requests per day per model
(20/day for the default answer model `gemini-3.8-flash` at the time of writing). If answers stop with a
"usage limit" message, switch the *Answer model* in Settings to `gemini-3.5-flash-lite`, wait for the
daily reset, or use your own key.

The first run downloads the local search models (~200 MB) once.

## 1. Start the app

Open a terminal in the project folder and activate the virtual environment, then start the server.

macOS / Linux:

```bash
cd sentinel-ops-rag-platform
source .venv/bin/activate
python -m src.web
```

Windows (PowerShell):

```powershell
cd sentinel-ops-rag-platform
.venv\Scripts\Activate.ps1
python -m src.web
```

You should see:

```
... INFO  [-] src.web: Starting Sentinel Ops RAG Platform v0.1.0 on http://127.0.0.1:7400
... INFO  [-] uvicorn.error: Uvicorn running on http://127.0.0.1:7400 (Press CTRL+C to quit)
```

Open **http://127.0.0.1:7400** in a browser. The first start after installation takes
10–30 seconds longer while the local search models load (they are downloaded once, into `.cache/`).

**Stop** the app with `Ctrl+C` in that terminal. **Restart** it the same way; your documents,
conversations and settings are kept on disk.

### Start on a different port

Set `WEB_PORT` in `.env` (for example `WEB_PORT=7401`) or for one run:

```bash
WEB_PORT=7401 python -m src.web          # Windows PowerShell: $env:WEB_PORT=7401; python -m src.web
```

### Keep it running in the background (macOS / Linux)

```bash
nohup python -m src.web > logs/server.out 2>&1 &
echo $! > .server.pid              # later: kill "$(cat .server.pid)"
```

The app is single-user and has no login, so keep `WEB_HOST=127.0.0.1` (the default). Do not expose
it on a network interface without putting authentication in front of it.

---

## 2. First five minutes

1. **Settings → AI providers**: confirm a key is set (green "key set ••••xxxx") or paste one. Click **Test models**.
2. **Documents → Try sample documents** to load the demo corpus: the 8 files directly in
   `data/sample_docs/` (subfolders are never auto-loaded). Or drag in your own files.
3. **Ask**: click a starter question, or type one. Expand **Sources** to see the cited passages and
   **Technical details** to see which agents ran.
4. Try the guardrails with the hand-upload folders in `data/sample_docs/`:
   `extra/` (accepted, newer subject areas), `offtopic/` (all rejected with a reason),
   `redteam/` (accepted with a prompt-injection warning).

---

## 3. Where everything lives

| What | Where | Notes |
|---|---|---|
| Configuration and API keys | `.env` | Created from `.env.example`. Keys saved on the Settings page are written here. Never committed. |
| Accepted documents | `data/uploads/` | Originals of every indexed file. `.staging/` holds files awaiting an "Add anyway" decision. |
| Search index | `data/qdrant/` | Embedded Qdrant. One process at a time: stop the app before running CLI tools that index. |
| Data tables | `data/tables.duckdb` | CSV/Excel contents for the Data Analyst's SQL. |
| History and settings | `data/app.db` | SQLite: conversations, upload history, document catalogue, preferences (models, switches). |
| Logs | `logs/app.log`, `logs/errors.log`, `logs/audit.log` | Rotated per `.env`. Secrets are masked before writing. |
| Local AI models | `.cache/fastembed/` | Embeddings, BM25 and reranker (~200 MB). Safe to delete; re-downloaded on next start. |
| Demo corpus | `data/sample_docs/` | Regenerate with `python -m scripts.generate_sample_data`. |
| Evaluation sets and results | `data/eval/` | `retrieval_golden.yaml`, `answer_golden.yaml`; results in `data/eval/results/`. |

Browser-side preferences (theme, font, text size) are stored in the browser, not in the app.

---

## 4. Routine tasks

### Add, remove or re-index documents

- **UI:** Documents page: drag files in, or **Remove** next to a document.
- **CLI** (stop the app first; the index allows one process):

```bash
python -m scripts.ingest data/sample_docs             # screen + index a folder
python -m scripts.ingest report.docx scan.csv         # individual files
python -m scripts.ingest --reindex                    # rebuild the index from data/uploads/
```

### Change the AI model or provider

Settings → **Models**: choose the *Answer model* and *Fast model* (lists are fetched from the provider
with your key), or type any `provider:model` under *Custom…*. **Test models** confirms both reply.
**Reset to defaults** returns to the `.env` values. Changes apply to the next question; no restart.

### Rotate an API key

Settings → **AI providers** → paste the new key → **Save**. It overwrites the value in `.env` and is used
immediately. To remove a key, click *remove*. (Editing `.env` by hand also works, but needs a restart.)

### Turn AI answers off (passages only)

Settings → **AI answers** switch. Useful for demonstrating retrieval, or to avoid API usage.

### Back up

Stop the app and copy the `data/` folder and `.env`. To restore, copy them back.
If only `data/uploads/` survives, run `python -m scripts.ingest --reindex` to rebuild the index and tables.

### Reset everything

Stop the app, then:

```bash
rm -rf data/uploads/* data/qdrant/* data/tables.duckdb* data/app.db logs/
```

The folders are recreated on the next start. `.env` and `.cache/` are kept.

### Delete history only

Settings → **Your data**: *Delete chat history* or *Delete upload history*. Documents stay indexed.

---

## 5. Health checks and the API

```bash
curl -s http://127.0.0.1:7400/api/health
# {"status":"ok","documents":8,"chunks":75,"ai_answers":true}
```

Interactive API docs: **http://127.0.0.1:7400/api/docs**. Examples:

```bash
curl -s -X POST http://127.0.0.1:7400/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "What is the patch SLA for critical vulnerabilities?"}'
curl -s -F files=@runbook.docx http://127.0.0.1:7400/api/documents
curl -s http://127.0.0.1:7400/api/conversations
```

Errors from the API always have the shape
`{"error": {"code", "severity", "message", "hint", "retryable", "reference", "request_id", "detail"}}`.

---

## 6. Reading the logs

| File | Look here when |
|---|---|
| `logs/errors.log` | Something failed. Search for the **reference** shown in the UI message (e.g. `ref=6dc76e7d`). Also visible in Settings → **Recent problems**. |
| `logs/app.log` | You want the full story: every request with status and duration, agent steps, retries. |
| `logs/audit.log` | Security review: uploads accepted/rejected and why, secrets found, injection flags, documents indexed/removed, blocked SQL, blocked questions, key and model changes. |

Each line carries a request ID in brackets, so one request's lines can be followed across files.
Verbosity, rotation (by size or time) and JSON output are set in `.env` (`LOG_*` variables).

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `address already in use` on start | Another program (or an old copy of the app) uses port 7400 | `pkill -f "src.web"`, or set `WEB_PORT` to a free port |
| "The knowledge base is already open in another program" (`STORE_LOCKED`) | A second process holds the embedded index (another app copy, `scripts.ingest`, an evaluation) | Stop the other process and retry; only one process may use `data/qdrant/` |
| Top bar says **AI answers off** | No key for the chosen models, or the switch is off | Settings → AI providers / AI answers; then **Test models** |
| Answers take 30–60 s or say "(strong model unavailable, used fast model)" | The provider reports the strong model overloaded (HTTP 503/504); the app retries twice then switches to the fast model for that question | Wait, or pick another answer model in Settings (e.g. `gemini-3.6-flash`) |
| "The AI service rejected the API key" | Wrong or revoked key | Paste a new key in Settings; create one at the provider's key page |
| "The configured AI model is not available" | Model retired or not enabled for your key | Settings → Models → pick from the live list; **Refresh list** |
| A question runs too long | Slow provider | Press **Stop**; the server cancels the agents. Ask again or rephrase |
| Upload "Not added" | See the **Why:** line: blocked type, unreadable, duplicate, or off-topic | Convert legacy `.doc/.xls`, remove macros, or use **Add anyway** when offered |
| Try sample documents says "already been added" | The corpus is already indexed | Nothing to do; or Remove and retry |
| Models dropdown shows "(built-in)" | No key for that provider, or its API was unreachable | Add the key; **Refresh list** |
| Page looks stale after an update | Browser cache | Reload once; assets are versioned by content so this is rare |
| Upload rejected as off-topic but it is relevant | The topic score fell below the threshold | Use **Add anyway** if offered; or lower `RELEVANCE_REJECT_MARGIN` slightly (e.g. `-0.02`) in `.env`. Adding examples of that subject in `src/guardrails/domains.py` is the better long-term fix |
| Logs grow too large | Verbose level or large rotation settings | Lower `LOG_MAX_MB` / `LOG_BACKUP_COUNT`, switch to `LOG_ROTATION=time`, or raise `LOG_LEVEL` to `WARNING` |
| Chat says the knowledge base is empty after a reset | Index deleted but documents still in `data/uploads/` | `python -m scripts.ingest --reindex` (app stopped) |
| Tests fail with "Storage folder … already accessed" | The app is running while tests index into the real folder (only `tests/test_*` that use temp folders are isolated) | Stop the app before running the full suite |

---

## 8. Security notes

- **Local only.** The server binds to `127.0.0.1`. There is no login; anyone with access to the machine can use it.
- **Keys** live in `.env` (file mode 0600 when written by the app) and are sent only to their provider.
- **Secrets in documents** (keys, passwords) are masked before indexing, in answers and in logs.
- **Uploaded text is untrusted.** Passages are passed to the AI as data; instructions hidden in documents are flagged, not followed.
- **SQL** written by the Data Analyst runs in a sandbox: read-only, single SELECT, no file or network access.

---

## 9. Evaluations

Stop the app first (the index allows one process), then:

```bash
python -m scripts.ingest data/sample_docs        # make sure the demo corpus is indexed
python -m src.evaluation.retrieval_eval          # retrieval benchmark, no API calls, ~1 min
python -m src.evaluation.answer_eval             # 13 questions through the agents, uses the API
python -m pytest -q                              # 196 offline tests
```

Results of `answer_eval` are saved to `data/eval/results/` with the models that were in use.
