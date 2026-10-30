# Sentinel Ops RAG Platform

An AI agent–based knowledge and decision-support system for **IT operations,
security and governance** teams: DevOps, CloudOps, SecOps, IT security, IT
governance, ITSM, AI governance, FinOps, business continuity and network
operations. Upload runbooks, postmortems, policies, cloud configs, SIEM exports,
vulnerability scans, change records and deployment logs, then ask questions in
natural language. LangGraph agents plan
the task, retrieve and grade evidence, query tables with SQL, and validate that
every answer is grounded in your documents.

Every upload is screened first. Only safe, parseable files that are about the
platform's subject areas reach the knowledge base.

> Generative AI and ML capstone project.
> Source repository: **https://github.com/apoorvaditya-varma/sentinel-ops-rag-platform**
> (public; the repository never contains the `.env` file).

| Document | Contents |
|---|---|
| [docs/HANDBOOK.md](docs/HANDBOOK.md) | **Operations handbook:** start and stop the app on localhost, daily use, where data lives, routine tasks, health checks, troubleshooting, packaging |
| [docs/SETUP.md](docs/SETUP.md) | **Setup guide:** first-time install on macOS / Linux / Windows, configuration reference, verification |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, upload screening, retrieval, multi-agent workflow, model selection, guardrails, evaluation, limitations, challenges |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Future work: deployment, quality and cost, new agents, knowledge management, UX, security, observability |

## Architecture

![Platform architecture](docs/architecture.svg)

## Quick start

```bash
cd sentinel-ops-rag-platform
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: see docs/SETUP.md
pip install -r requirements.txt
cp .env.example .env                                     # set GOOGLE_API_KEY (or add keys later in Settings)
python -m scripts.check_setup
python -m src.web                                        # http://127.0.0.1:7400  (Ctrl+C to stop)
```

Open **Documents → Try sample documents** to load the demo corpus, then ask a question on **Ask**.
With a key set, a team of agents answers with citations; without one (or with AI answers switched off in
Settings) the chat shows the most relevant passages with their sources. Day-to-day start/stop, data
locations and troubleshooting are in the [operations handbook](docs/HANDBOOK.md).

## How questions are answered (multi-agent)

A **supervisor** agent plans which **specialist agents** to use, based on their registered capabilities
(`src/agents/registry.py`). Later specialists receive earlier findings:

| Agent | Capability | Tools |
|---|---|---|
| Supervisor | Understands the question (including follow-ups), handles greetings and off-topic requests, plans the steps | — |
| Document Researcher | Policies, runbooks, postmortems, configs. Searches, grades the evidence, rewrites the query and retries | hybrid search + reranker |
| Data Analyst | Counts, filters and lists over CSV/Excel | `list_tables`, `describe_table`, `run_sql` (sandboxed DuckDB) |
| Answer Writer | Writes the answer only from the findings, citing `[S1]` passages and `[T1]` query results | — |
| Reviewer | Checks every claim is supported; sends the answer back once, otherwise adds a caveat | — |

Example: *"How many open critical findings are past their SLA, and what does our policy say?"* runs the
**Researcher** (finds the 7-day SLA), then the **Analyst** (SQL over the scan with that SLA as context), then the
**Writer** and the **Reviewer**. The chat shows "Answered by …" with the time taken, citation badges, and the full agent trace under
*Technical details*. While a question runs you see the elapsed seconds, a status that changes as the work
progresses, and a **Stop** button; stopping cancels the agents on the server so no further AI calls are made. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#multi-agent-workflow-tasks-7-8).

## Using the app

| Page | What you can do |
|---|---|
| **Ask** (home) | Chat about your documents. Four example questions appear on an empty chat, drawn at random from a pool and limited to questions the indexed documents can answer (so they change as you upload more; *Shuffle questions* redraws them), and **Upload documents** links in the sidebar and on the welcome screen lead to the Documents page. Answers show "Answered by …" with the time taken and citation badges; **Sources** and **Technical details** (agent trace, scores) are collapsed underneath. While a question runs you see elapsed seconds, a changing status and a **Stop** button; leaving the page does not stop the answer, it is saved to the conversation for when you return. Past conversations are listed in the **History** sidebar (Today / Yesterday / Previous 7 days / Older) and can be reopened or deleted; the **Ask** tab returns to the conversation you were last in, and **New chat** starts a fresh one. You can also limit the search to selected documents. |
| **Documents** | Drag and drop files or **Try sample documents**. Each file gets a plain-language result: *Added*, *Not added* with a **Why:** line naming the check that failed (file type, duplicate, readability or topic) and the cause or *Needs your confirmation* (choose *Add anyway* or *Don't add*). The list shows friendly names, file type, topics, date added and warnings such as "passwords were hidden". **Details** and **Upload history** are collapsed. |
| **Settings** | Appearance: theme (System / Light / Dark), font (Modern / Classic / Mono) and text size (Small / Normal / Large); the *Technical details* switch; **AI answers** on/off; **AI providers** (paste a Google, OpenAI or Anthropic key, stored in `.env`); **Models**: choose the answer model and the fast model from live-fetched lists (or type any `provider:model`), **Test models**, reset to the `.env` defaults; deleting chat or upload history. Every setting has an ⓘ tooltip explaining what it does. **System details** and **Recent problems** are collapsed. |

The theme switch in the top bar (☀ / 🖥 / ☾) and the font and text-size choices in Settings are remembered in the browser.
The layout works on phones: the History sidebar slides in from the menu button.

Full instructions, Windows commands and troubleshooting are in [docs/SETUP.md](docs/SETUP.md).

## Subject areas accepted

| Domain | Examples |
|---|---|
| DevOps & SRE | CI/CD, deployments, Kubernetes, IaC, monitoring, runbooks, postmortems |
| IT governance, compliance & code security | Policies, audits, ISO 27001 / SOC 2 / PCI DSS / NIST / GDPR, secure coding, AppSec |
| CloudOps | AWS / Azure / GCP accounts, IAM, compute, storage, landing zones, cloud security posture |
| SecOps | SIEM alerts, detection, incident response, threat intel, MITRE ATT&CK, vulnerability management |
| IT security | Identity & MFA, endpoint and network security, encryption, secrets, data protection |
| IT service management (ITIL) | Incident / problem / change management, CAB, service desk SLAs, CMDB |
| AI / LLM governance & security | AI policies, model risk, LLM security, NIST AI RMF, EU AI Act, ISO 42001, model cards |
| FinOps (cloud cost) | Cloud spend reports, cost allocation and tagging, rightsizing, savings plans |
| Business continuity & resilience | BIA, DR plans and tests, backups and restores, RTO/RPO, crisis management, DORA |
| Network operations | Routing, firewall rules, VPN, DNS, load balancers, SD-WAN, network changes |

Domains are defined in [src/guardrails/domains.py](src/guardrails/domains.py), and adding one takes a single entry.
Anything else (HR, general finance and accounting, sales, marketing, facilities…)
is rejected or, if borderline, sent for an LLM decision or manual review.

## Supported file types

| Accepted | Use for |
|---|---|
| `.pdf` `.docx` | Policies, standards, audit reports, runbooks, SOPs |
| `.md` `.txt` | Wiki pages, playbooks, notes |
| `.log` | Application, audit and system logs |
| `.csv` `.xlsx` | SIEM alerts, scan results, inventories, risk registers |
| `.json` | Cloud configs, IAM policies, SIEM/scanner exports (JSON or JSON Lines) |
| `.yaml` `.yml` | Kubernetes manifests, CI/CD pipelines, Ansible playbooks |

**Blocked, with a reason shown to the user:**
- legacy `.doc` and `.xls` (the message asks for `.docx`/`.xlsx` instead)
- macro-enabled Office files
- executables and scripts
- archives
- images (no OCR)

## Guardrails

| When | What | Status |
|---|---|---|
| Upload: file type | Allow/block lists; magic-byte checks; macro, zip-bomb and double-extension detection; size and page limits; filename sanitising; duplicate detection | ✅ |
| Upload: topic | Local embedding margin vs off-topic prototypes. Borderline files go to the fast LLM classifier, otherwise to *needs review* | ✅ |
| Upload: content | Secret detection (cloud keys, tokens, private keys, passwords) and prompt-injection detection, reported as warnings | ✅ |
| Quarantine | Files are held in `data/uploads/.staging` until accepted | ✅ |
| Indexing | Secrets masked in every chunk; injection-flagged chunks stored with `untrusted=true` and labelled in the UI | ✅ |
| SQL sandbox | DuckDB with external access disabled and config locked (no file/network reads, COPY, ATTACH, INSTALL); single SELECT only; row cap; 10 s timeout | ✅ |
| Question | Override and prompt-extraction attempts blocked (quoted text exempt), secrets masked, length limit, off-topic refused | ✅ |
| Prompting | Passages and table rows wrapped as untrusted data; prompts say to ignore instructions inside them | ✅ |
| Answer | Reviewer groundedness check with one revision, mandatory citations (invalid ones removed), "couldn't find this" when evidence is missing, secrets masked, caveats | ✅ |
| Runtime | Retries with backoff, LLM timeout, recursion limit, bounded loops, fallback to passages if writing fails | ✅ |

## Retrieval quality

Measured on 24 golden questions over the sample corpus, counting a hit only when the chunk that
contains the answer is retrieved: the configuration in use (hybrid search + reranker + identifier
pinning) finds the answer passage in the top 5 for **100%** of questions and at rank 1 for **83%**
(MRR 0.91), against 71% / 50% for dense-only search. Hybrid search is what makes identifier queries
(CVE, IP, ticket IDs) work, and identifier pinning stops the reranker demoting exact matches. The full
comparison of five configurations and the method are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#retrieval-evaluation-srcevaluationretrieval_evalpy).

## Answer quality

`python -m src.evaluation.answer_eval` runs 13 golden questions through the full agent pipeline: document
facts, table counts, a researcher → analyst collaboration, a question the documents don't cover, an
off-topic request and a prompt-injection attempt. Result on 2026-10-30 (`gemini-3.5-flash-lite`):
**13/13 correct intent, 10/10 correct routing, fact recall 1.00, 3/3 numbers correct (truth computed live
by SQL), 8/8 cited sources correct, faithfulness 1.00 and relevance 1.00** by an LLM judge, 14 s per
question on average. The one question without a citation is the correct "I couldn't find this in your
documents" reply. The set is small and synthetic, so it shows the pipeline works end to end rather than
how it would score on unseen documents; details in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#evaluation-task-10).

## Error handling and logging

**Severity levels.** Every failure is converted to an `AppError` (`src/errors.py`) with a severity,
an error code, a plain-language message, a hint and a reference ID:

| Severity | Meaning | Examples | HTTP |
|---|---|---|---|
| `info` | The user can fix it | Empty question, invalid request | 400 / 422 |
| `warning` | Temporary or degraded; retrying may work | AI rate limit, network timeout, AI not configured, item not found | 429 / 503 / 404 |
| `error` | The action failed | Bad API key, model not found, unreadable file, storage error | 500 / 502 |
| `critical` | Needs an operator | Invalid configuration, knowledge base locked by another process | 500 / 503 |

- **In the UI:** the user sees a coloured message (blue, amber or red) with the hint. A collapsed **Details** section holds *What happened* (the underlying cause, secrets masked), the error code, and a reference to search in the right log file (`errors.log` for warnings and above, `app.log` for info). There is never a stack trace.
- **In the API:** errors use a single shape, `{"error": {code, severity, message, hint, retryable, reference, request_id}}`.
- **Retries:** rate limits and timeouts are marked `retryable`, and `retry_transient` retries them with exponential backoff.
- **Batch uploads:** one broken upload never fails the rest of the batch.

**Logs** (`logs/`, configured in `.env`):

| File | Contents |
|---|---|
| `app.log` | Everything at `LOG_LEVEL` and above, including every request with its status and duration |
| `errors.log` | Warnings and above, with tracebacks (the **Recent problems** panel in Settings) |
| `audit.log` | Security events: rejected uploads, secrets found, injection flags, indexed and removed documents, blocked SQL |

**Rotation options:**
- `LOG_ROTATION=size`: rotate at `LOG_MAX_MB`
- `LOG_ROTATION=time`: rotate every `LOG_ROTATE_WHEN` (`midnight`, `H`, `D`, `W0`-`W6`)
- `LOG_ROTATION=off`: no rotation

`LOG_BACKUP_COUNT` sets how many old files are kept. `LOG_FORMAT=json` writes one JSON object per
line for log shippers and SIEMs. Every line carries the request ID, so the reference shown in the UI
can be traced in the logs. **Secrets are masked before anything is written.**

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Agents | LangGraph 1.2 + LangChain 1.4 | Explicit, inspectable agent graph with bounded loops |
| LLMs | Default Gemini 3.8 Flash (answers) + Gemini 3.5 Flash-Lite (planning, grading, review); switchable in Settings to any Google, OpenAI or Anthropic model (`langchain-google-genai`, `langchain-openai`, `langchain-anthropic`) | Strong and cheap models for different steps; one code path (`init_chat_model`) for all providers; per-request circuit breaker to the fast model when the strong one is overloaded |
| Vector store | Qdrant, embedded local mode | Native hybrid dense + BM25 search, no server or Docker |
| Embeddings | `BAAI/bge-small-en-v1.5` + `Qdrant/bm25` (FastEmbed, ONNX) | Local, free, no PyTorch; about 70 MB |
| Reranker | `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder | Fast, accurate second-stage ranking |
| Tables | DuckDB | Exact aggregates over CSV / Excel via read-only SQL |
| Parsing | pypdf, python-docx, pandas/openpyxl, PyYAML | Pure-Python parsers that are safe on untrusted input |
| Web UI | FastAPI + Jinja2 + HTMX 2 (bundled locally, ~50 KB) + one hand-written CSS file | No Node/build step, works offline, light/dark themes, the same backend serves the REST API |
| App state | SQLite (`data/app.db`) | Chat history, upload history, document catalogue, preferences |

## Sample data

`python -m scripts.generate_sample_data` regenerates a synthetic corpus for the
fictional company *Northwind Cloud*. CVE and MITRE ATT&CK IDs are real public
identifiers; everything else is invented.

**Try sample documents** loads only the files directly in `data/sample_docs/` (the 8 core
documents below). The subfolders `extra/`, `offtopic/` and `redteam/` are never auto-loaded:
upload them by hand from the Documents page to see screening, rejections and the newer subject areas.

| File | Format | Content |
|---|---|---|
| `information_security_policy.pdf` | PDF | MFA, data classification, patch SLAs, severity levels |
| `incident_response_plan.pdf` | PDF | NIST 800-61 phases, roles, communication rules |
| `runbook_k8s_crashloopbackoff.txt` | TXT | Kubernetes troubleshooting runbook |
| `runbook_leaked_credentials.txt` | TXT | Credential-leak response (contains AWS's documented example keys, to test secret detection) |
| `postmortem_INC-2041_payment_api_outage.txt` | TXT | SEV1 postmortem |
| `vulnerability_scan_2026Q3.xlsx` | Excel | 48 scan findings with CVSS, KEV flag and SLA dates |
| `siem_alerts_2026-10.csv` | CSV | 90 SIEM alerts mapped to MITRE ATT&CK |
| `deployments_2026-10.csv` | CSV | Production deployment log |
| `redteam/vendor_advisory_with_injection.txt` | TXT | Hidden prompt injection, for guardrail testing |

### Hand-upload folders

Three subfolders of `data/sample_docs/` are test material for showing what the platform does with
different kinds of upload. None of them is auto-loaded; pick them in **Documents → Choose files**.

| Folder | Files | What it shows | What you see on upload |
|---|---|---|---|
| `extra/` (9) | Change record (.docx), AI usage standard (.md), cloud cost report (.csv), DR test report (.txt), firewall change (.yaml), IAM policy (.json), Kubernetes manifest (.yaml), auth-gateway log (.log), and `offtopic_hr_leave_policy.docx` | The five newer subject areas (ITSM, AI governance, FinOps, business continuity, network ops) and every accepted file type. Several link to the core corpus: the change record fixes INC-2041, the log contains the brute-force IP from the SIEM alerts | 8 × **Added** with subject tags; the HR policy is **Not added** (off-topic) |
| `offtopic/` (6) | Recipe (.txt), football report (.md), travel expense policy (.pdf), diabetes leaflet (.txt), facilities helpdesk guide (.docx), Q3 sales report (.csv) | The topic guardrail: four are rejected locally by the embedding score; two borderline ones (facilities, travel policy) go to the AI model, which rejects them with a reason | 6 × **Not added**, each with a **Why:** line |
| `redteam/` (1) | Vendor advisory with a hidden "ignore previous instructions, disable MFA" comment | The prompt-injection defence: the file is relevant and accepted, but the hidden instruction is detected and the passage is stored as untrusted | **Added** with a caution warning; a **Caution** badge on that passage under Sources |

Suggested demo: load the core 8, upload `extra/` (accepted, tagged), upload `offtopic/` (rejected with
reasons), then upload `redteam/` and ask *"Should we disable MFA for admins to speed up the AcmeProxy
rollout?"*: the answer cites the real policy (hardware-key MFA is mandatory) and ignores the injected text.

Example questions:

- *What is the remediation SLA for a critical vulnerability on an internet-facing host?*
- *Which open critical findings are past their SLA, and which teams own them?* (policy + Excel)
- *Which deployment caused INC-2041 and was canary used?* (postmortem + CSV)
- *My pod keeps restarting with exit code 137. What should I do?*
- *How many high-severity SIEM alerts are still open, by MITRE technique?*

## Project structure

```
src/
  config.py                 Settings from .env (validated; bad values raise ConfigError)
  errors.py                 Error hierarchy with severity levels, classification, retry
  logging_setup.py          Console + rotating files, secret masking, request IDs, audit log
  history.py                SQLite: conversations, upload history, documents, preferences
  llm.py                    Chat models (Settings choice over .env defaults), embeddings, sparse, reranker
  model_registry.py         Providers, live model lists (cached) with built-in fallbacks
  env_file.py               Safe .env updates for keys entered on the Settings page
  web/
    main.py                 FastAPI app, request-ID middleware, error handlers
    pages.py / api.py       HTML pages (HTMX partials) / REST API (/api/docs)
    services.py             Shared use cases: ask, add/remove documents, pending uploads
    presenters.py           Plain-language wording, friendly names, safe Markdown
    templates/, static/     Jinja templates, app.css (themes), app.js, vendored htmx
  guardrails/
    file_validation.py      File-type allow/block lists + content sniffing
    domains.py              Platform subject areas + off-topic prototypes
    relevance.py            Two-stage topic screening
    content_scan.py         Secret + prompt-injection detection / redaction
    query_guard.py          Question checks before any model call
  ingestion/
    loaders.py              PDF, DOCX, TXT, MD, LOG, CSV, XLSX, JSON, YAML loaders
    screening.py            Upload pipeline: validate → stage → parse → scan → relevance
    chunking.py             Structure-aware chunks, source headers, redaction, untrusted flag
    pipeline.py             Index / remove / re-index files (Qdrant + DuckDB)
  vectorstore/store.py      Embedded Qdrant: dense + BM25 vectors, RRF fusion
  retrieval/retriever.py    Hybrid search → rerank → identifier pinning
  tables/sql_store.py       Sandboxed DuckDB for CSV/Excel
  rag/chain.py              Numbered sources (S#/T#), grounded answer generation, citation clean-up
  agents/
    registry.py             Capability registry of specialist agents
    graph.py                LangGraph workflow: supervisor → specialists → writer → reviewer → finalize
    prompts.py              All agent prompts
    state.py                Shared state + structured outputs (Plan, Grade, Review)
    tools.py                Sandboxed SQL tools for the Data Analyst
  evaluation/
    retrieval_eval.py       Retrieval benchmark (5 configurations, no LLM)
    answer_eval.py          Answer quality: facts, numbers, sources, routing, faithfulness, relevance
scripts/
  check_setup.py            Environment + model verification
  ingest.py                 Screen + index files / folders from the CLI; --reindex
  generate_sample_data.py   Synthetic corpus
  draw_architecture.py      Renders docs/architecture.svg
data/
  sample_docs/              Demo corpus (+ extra/, offtopic/, redteam/ for hand uploads)
  eval/                     retrieval_golden.yaml (24 questions), answer_golden.yaml (13 questions)
docs/                       HANDBOOK.md, SETUP.md, ARCHITECTURE.md, architecture.svg
tests/                      pytest suite (offline, 199 tests)
```

## Progress

| # | Task | Status |
|---|---|---|
| 1 | Project foundation | ✅ |
| 2 | User interaction layer | ✅ web UI (Ask with history, Documents, Settings; light/dark) + REST API |
| 3 | Document ingestion (multi-format) | ✅ loaders + screening |
| 4 | Chunking | ✅ |
| 5 | Vector store | ✅ Qdrant hybrid + DuckDB |
| 6 | Retrieval | ✅ hybrid + rerank + identifier pinning, benchmarked |
| 7 | RAG pipeline | ✅ grounded answers with citations; runs live against Gemini |
| 8 | Agents | ✅ supervisor + researcher + analyst + writer + reviewer; circuit breaker, cancellation (Stop) |
| 9 | Reliability & safety | ✅ upload, indexing, SQL, question, prompt and answer guardrails; error levels; logging with rotation |
| 10 | Deployment & docs | ✅ runs locally (handbook, setup guide, architecture, diagram); retrieval and answer evaluations recorded |

## Future work

The app is complete for a single user on one computer. [docs/ROADMAP.md](docs/ROADMAP.md) lists the
next steps with reasoning and rough effort: deployment (a Docker image, left out of this submission on
purpose, Qdrant as a service, login, CI), answer quality and cost (streaming, parallel agent steps,
caching, quota-aware model switching), new agent capabilities (ticket, metrics and compliance agents,
approved actions), knowledge management (scheduled ingestion, document versions and freshness,
collections, coverage gaps, OCR), user experience (feedback, export and sharing, chat integrations),
security and compliance (permission-filtered retrieval, PII classification, secrets vault, data residency)
and observability.

## Tests

```bash
python -m pytest -q                       # 199 tests, offline (no API key needed), ~40 s
python -m src.evaluation.retrieval_eval   # retrieval benchmark (needs the sample corpus indexed)
python -m src.evaluation.answer_eval      # answer quality, 13 golden questions (needs GOOGLE_API_KEY)
```

They cover:
- accepted and blocked file types, plus spoofed and malicious files
- secret and injection detection
- relevance accept/reject across all 10 subject areas, off-topic text and near-misses (invoice, helpdesk, expenses)
- the end-to-end screen → promote → duplicate flow
- chunk sizes, headers, row ranges, masking and deterministic IDs
- indexing all formats into a temporary Qdrant + DuckDB, idempotent re-indexing and deletion
- retrieval of answer passages for paraphrase and identifier queries, plus source filters
- the SQL sandbox: DROP, DELETE, multiple statements, `read_csv` file access and internal tables are all rejected
- web pages and API: conversations and history, the technical-details toggle, HTML escaping, uploads with
  explanations, needs-review → *Add anyway*, removal, and the error format and status for each severity
- error classification, transient retries, the three log-rotation modes, log levels per file, secret masking
  in logs, JSON logs with request IDs, and config validation
- the multi-agent workflow with scripted models (real LangChain structured-output and tool-calling code paths):
  - the document flow, and the corrective retry and its bound
  - the analyst's SQL tool loop and error recovery
  - researcher → analyst collaboration
  - direct replies and dropping invalid plan steps
  - follow-up questions using chat history
  - reviewer revision and caveats
  - secret masking in answers
  - model outages, with the fallback to passages
- question guard (override attempts vs quoted mentions), the answer-evaluation harness, and history migration
- Stop/cancellation, the strong→fast circuit breaker, and the overload (503/504) classification
- Settings: provider model lists (live, cached, fallback), `.env` key writes, model choice and validation,
  the AI-answers switch, the *Test models* endpoint, and the appearance controls
