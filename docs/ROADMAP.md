# Roadmap — Sentinel Ops RAG Platform

The platform is complete for its purpose: one user, one computer, documents about IT operations,
security and governance. This roadmap lists what would make it more useful, cheaper or safer if it were
taken further. Items are grouped by theme; the final section suggests an order.

Effort is a rough guide: **S** = a day or two, **M** = about a week, **L** = several weeks.

---

## 1. Deployment and operations

| Item | Why | What it involves | Effort |
|---|---|---|---|
| **Docker image** | One command to run on any machine, no Python setup; the natural way to hand the app to graders, colleagues or a server. It was deliberately left out of this submission (the brief asks for a local run, and an image adds build time and ~2 GB without changing what the user sees), but the code is ready: all configuration is in `.env`, all state is under `data/`, and there are no system services. | `Dockerfile` (python:3.12-slim, requirements, local models pre-downloaded so first start is instant), `docker-compose.yml` with volumes for `data/` and `logs/`, keys via environment or a mounted `.env`, port 7400 published, a `/health` healthcheck. | S |
| **Qdrant as a service** | The embedded index allows one process, which blocks CLI indexing and evaluations while the app runs and rules out multiple instances. | Second container running `qdrant/qdrant`; `KnowledgeStore` already uses the client API, so it is a URL change plus removing the process lock. | S |
| **Authentication and users** | Anyone on the machine can use the app, and history is shared. Required before exposing it beyond `127.0.0.1`. | Login (OIDC against the company identity provider, or a local login), per-user conversations and preferences, audit log keyed by user. | M |
| **Reverse proxy and TLS** | Needed for any network deployment. | Caddy or nginx in front of uvicorn, TLS, request size limits, rate limiting per user. | S |
| **CI/CD** | Catch regressions on every change; publish the image. | GitHub Actions: `pytest` (offline) and `retrieval_eval` on every push; `answer_eval` on a schedule with a paid key; build and push the image on tags. | S |
| **Backups and retention** | Protect the knowledge base and meet retention rules. | Scheduled copy of `data/` and `.env`, retention settings for conversations and upload history, restore runbook. | S |

## 2. Answer quality, speed and cost

| Item | Why | What it involves | Effort |
|---|---|---|---|
| **Streaming answers** | The user sees the answer being written instead of a timer. | Server-sent events from the writer step; the HTMX front end already supports swapping fragments. | M |
| **Parallel agent steps** | Grading passages and independent specialist steps run one after another today. | Grade passages concurrently; let the supervisor mark steps as parallelisable; LangGraph supports fan-out. | M |
| **Caching** | Fewer model calls and faster repeat questions. | Embedding cache for unchanged chunks on re-index; provider prompt caching for the fixed parts of prompts; short-lived cache of identical questions. | S–M |
| **Quota-aware model switching** | The free tier exhausts the default model after ~10 questions a day; today the user switches in Settings. | Read the provider's 429 `RetryInfo`, switch to the next configured model automatically for the rest of the window, show a banner. | S |
| **Conversation memory** | Follow-ups work through question rewriting only; the writer does not see earlier answers. | Pass a summary of the conversation to the writer; keep per-conversation facts (e.g. "the user's team is payments"). | S |
| **Query decomposition** | Multi-part questions ("compare X and Y, then …") are planned as sequential steps but answered once. | Let the supervisor emit sub-questions with their own research, and a merge step. | M |
| **Better reranking / embeddings** | Retrieval quality on real, messy documents. | Evaluate larger local models (bge-base, Qwen3-Embedding-0.6B) or a GPU reranker; keep the benchmark as the gate. | S |
| **Larger evaluation sets** | 24 + 13 golden questions are small. | Build sets from real (anonymised) documents and user feedback; add a regression gate on faithfulness and fact recall. | M |

## 3. New agent capabilities

The registry makes a specialist a single entry plus a node. Candidates:

| Specialist | Capability | Tools | Effort |
|---|---|---|---|
| **Ticket agent** | Look up and summarise incidents, changes and problems from the live ITSM tool. | ServiceNow / Jira Service Management APIs (read-only). | M |
| **Metrics & logs agent** | Answer "what happened on host X at 09:12" from monitoring. | Prometheus / Loki / Elasticsearch queries with time windows. | M |
| **Compliance mapper** | "Which ISO 27001 / SOC 2 controls does this policy cover, and what is missing?" | Control catalogues loaded as tables; the researcher for policy text. | M |
| **Remediation planner** | Turn a finding (CVE, failed DR step) into a step-by-step plan with owners, drawn from runbooks and change records. | Existing researcher + analyst, new prompt and output format. | S |
| **Change-impact agent** | "What changed since last week, and which runbooks are affected?" | Document versioning (see §4) plus diffing. | M |
| **Action tools with approval** | Let agents *do* things (open a ticket, page on-call) only after a human approves, using LangChain's human-in-the-loop middleware. | Approval UI, audit of every action. | M |

## 4. Knowledge management

| Item | Why | What it involves | Effort |
|---|---|---|---|
| **Scheduled ingestion from sources** | Documents live in Confluence, SharePoint, Git and ticketing tools, not on disk. | Connectors that pull on a schedule, with the same screening pipeline; incremental re-index of changed pages. | L |
| **Document versions and freshness** | Policies expire; stale runbooks cause incidents. | Keep versions, show "last reviewed" dates, warn when a cited document is older than its review period, let owners mark documents as superseded. | M |
| **Collections / workspaces** | Teams want their own scope ("payments runbooks only"). | Tag documents into collections; scope questions and access by collection. | M |
| **Near-duplicate detection** | Two versions of the same policy produce conflicting answers. | Similarity check at upload with a "looks like an existing document" prompt. | S |
| **Suggested tags and owners** | Make the catalogue searchable and accountable. | The fast model proposes tags and an owning team at upload; the user confirms. | S |
| **Coverage gaps** | Learn what the knowledge base is missing. | Record questions answered with "couldn't find this"; show them as a list of documents to add. | S |
| **OCR and images** | Scanned PDFs and screenshots are rejected today. | Tesseract or a vision model at ingestion, flagged as lower-confidence text. | M |
| **Very large spreadsheets** | 100k+ rows would bloat the vector index. | Load into DuckDB only, with a schema chunk and sampled rows in the index. | S |

## 5. User experience

| Item | Why | Effort |
|---|---|---|
| **Feedback on answers** (helpful / not, with a reason) feeding the evaluation set and the coverage-gap list | Turns use into quality data | S |
| **Export and share**: copy an answer with its sources, export a conversation to Markdown/PDF, share a link to a conversation | Answers end up in tickets and postmortems | S |
| **Saved and pinned answers**, and follow-up suggestions after each answer | Faster repeat use | S |
| **Chat integrations** (Slack / Microsoft Teams bot) | Meet users where incidents are discussed | M |
| **Keyboard shortcuts, command palette, mobile PWA install** | Daily-use polish | S |
| **Multilingual documents and questions** | Multilingual embedding model (bge-m3) and prompts; UI translations | M |
| **Accessibility pass** (WCAG 2.1 AA audit, screen-reader labels, reduced-motion review) | Inclusive use; often a procurement requirement | S |

## 6. Security and compliance

| Item | Why | Effort |
|---|---|---|
| **Role-based access to documents** (per collection or classification) with the retrieval filtered by permission, not just the UI | Required once more than one team uses it | M |
| **PII and classification detection** at upload (beyond secrets): flag Restricted data, apply retention | Policy compliance for uploaded content | M |
| **Secrets in a vault** instead of `.env` (OS keychain locally; Vault / cloud secret manager when deployed) | Removes plain-text keys | S |
| **Audit export to the SIEM** (JSON logs are already available) and tamper-evident audit log | Security operations want the trail in one place | S |
| **Stronger prompt-injection defence**: a small classifier on retrieved chunks, canary tokens in prompts, an LLM-judge gate for high-risk answers | Pattern matching is the current first line | M |
| **Rate limiting and abuse controls** per user; content filters on questions | Needed for a shared deployment | S |
| **Data residency**: pin the provider region or use a local LLM (Ollama) for sensitive deployments | Some organisations cannot send text to a cloud provider | M |

## 7. Observability and quality engineering

- **Tracing** per agent step (LangSmith or OpenTelemetry, one `.env` switch): tokens, latency and cost per question; compare prompt versions.
- **Usage analytics** page: questions per day, most-asked topics, answer modes, failure rates, provider spend.
- **Prompt and model A/B tests** using the evaluation harness, with results stored next to the prompts.
- **Synthetic question generation** from new documents to grow the golden set automatically.

---

## Suggested order

1. **Quick wins (S):** quota-aware model switching, answer feedback, export/share, coverage gaps, near-duplicate detection, Docker image, CI.
2. **Multi-user readiness (M):** authentication, collections with permission-filtered retrieval, Qdrant service, reverse proxy, secrets vault, audit export.
3. **Depth (M–L):** streaming and parallel steps, conversation memory, ticket and metrics agents, scheduled ingestion with versioning and freshness, OCR.
4. **Scale and assurance:** larger evaluation sets with regression gates, tracing and analytics, stronger injection defences, data residency options.
