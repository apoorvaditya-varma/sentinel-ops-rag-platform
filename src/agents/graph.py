"""Task 8: multi-agent workflow (LangGraph).

    supervisor ──plan──▶ [researcher | analyst]* ──▶ writer ──▶ reviewer ──▶ finalize
        │                    (in planned order,          ▲          │
        └─smalltalk/out-of-scope──▶ direct ──┐           └─rejected─┘ (max MAX_ANSWER_RETRIES)
                                             └──────────────────────────────▶ finalize

- Supervisor (fast LLM): intent, standalone question, ordered plan of specialists.
- Document Researcher (fast LLM + hybrid search): search → grade → rewrite query → retry (bounded).
- Data Analyst (strong LLM tool-calling agent): list_tables / describe_table / run_sql in the DuckDB sandbox,
  receives earlier findings as context (e.g. an SLA from a policy).
- Writer (strong LLM): cited answer from numbered sources only (src/rag/chain.py).
- Reviewer (fast LLM): groundedness check; can send the answer back to the writer once.
- Finalize: output guard (secret masking, citation clean-up, caveats).

Every step appends to `trace`, shown to users under "How this answer was produced".
LLM failures degrade gracefully (fallback plan, keep all passages, skip review);
only a writer failure aborts, and the web layer then falls back to showing passages.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from src.agents import prompts
from src.agents.registry import ALL_AGENTS, SPECIALISTS, specialist_menu
from src.agents.state import AgentState, Finding, Grade, Plan, PlanStep, Review
from src.agents.tools import make_sql_tools
from src.config import get_settings
from src.errors import classify_exception, report, retry_transient
from src.guardrails.content_scan import redact_secrets
from src.rag.chain import NOT_FOUND, build_sources, clean_citations, format_sources, generate_answer
from src.retrieval.retriever import retrieve
from src.tables.sql_store import TableStore, get_table_store

log = logging.getLogger(__name__)

MAX_PLAN_STEPS = 3
UNVERIFIED = "This answer could not be checked automatically. Please verify it against the sources."
UNSUPPORTED = "Parts of this answer may not be fully supported by your documents. Please check the sources."
NO_CITATIONS = "This answer has no citations. Please verify it against the sources."
SMALLTALK_REPLY = "Hello! Ask me anything about your IT, security and operations documents."
OUT_OF_SCOPE_REPLY = ("I can only help with questions about your IT operations, security and governance documents, "
                      "such as policies, runbooks, incidents, alerts and scan reports.")


@dataclass
class Models:
    strong: BaseChatModel
    fast: BaseChatModel


def default_models() -> Models:
    from src.llm import get_chat_model, get_fast_chat_model

    return Models(get_chat_model(), get_fast_chat_model())


@dataclass
class AgentResult:
    intent: str
    question: str
    answer: str
    sources: list[dict]
    cited: list[str]
    plan: Plan | None
    review: Review | None
    caveat: str | None
    trace: list[dict]

    @property
    def agents_used(self) -> list[str]:
        seen = []
        for step in self.trace:
            if step["agent"] in SPECIALISTS and step["agent"] not in seen:
                seen.append(step["agent"])
        return seen


def _call(fn, *args):
    """Invoke an LLM-backed callable with retries on transient errors (rate limits, overload, timeouts)."""
    settings = get_settings()
    return retry_transient(attempts=settings.llm_retry_attempts, base_delay=2.0)(fn)(*args)


def _trace(state: AgentState, agent: str, action: str, detail: str, started: float) -> list:
    entry = {"agent": agent, "action": action, "detail": detail, "ms": int((time.perf_counter() - started) * 1000)}
    return [*state.get("trace", []), entry]


def _history_text(history: list[dict]) -> str:
    turns = history[-6:]
    return "\n".join(f"{t['role']}: {t['content'][:300]}" for t in turns) or "(none)"


def build_graph(models: Models, tables: TableStore):
    settings = get_settings()

    # ---- supervisor -----------------------------------------------------------
    def supervisor(state: AgentState) -> dict:
        started = time.perf_counter()
        scope = state.get("scope")
        available = tables.tables(scope)
        table_text = ", ".join(available) if available else "none"
        prompt = prompts.SUPERVISOR.format(menu=specialist_menu(), tables=table_text,
                                           history=_history_text(state.get("history", [])), question=state["question"])
        try:
            plan: Plan = _call(models.fast.with_structured_output(Plan).invoke, prompt)
            note = ""
        except Exception as exc:  # noqa: BLE001 - degrade to a safe default plan
            report(exc, "supervisor planning", log)
            plan = Plan(intent="answer", standalone_question=state["question"],
                        steps=[PlanStep(agent="researcher", task=state["question"])])
            note = " (planner unavailable, using default plan)"

        steps = [s for s in plan.steps if s.agent in SPECIALISTS and (s.agent != "analyst" or available)]
        if plan.intent == "answer" and not steps:
            steps = [PlanStep(agent="researcher", task=plan.standalone_question or state["question"])]
        plan.steps = steps[:MAX_PLAN_STEPS]
        plan.standalone_question = plan.standalone_question or state["question"]

        if plan.intent == "answer":
            detail = "Plan: " + " → ".join(ALL_AGENTS[s.agent].title for s in plan.steps) + note
        else:
            detail = f"Handled directly ({plan.intent.replace('_', ' ')})"
        return {"plan": plan, "step_index": 0, "findings": [], "write_attempts": 0, "review": None,
                "trace": _trace(state, "supervisor", "plan", detail, started)}

    def next_step(state: AgentState) -> str:
        plan = state["plan"]
        if plan.intent != "answer":
            return "direct"
        index = state.get("step_index", 0)
        return plan.steps[index].agent if index < len(plan.steps) else "writer"

    def direct(state: AgentState) -> dict:
        plan = state["plan"]
        default = SMALLTALK_REPLY if plan.intent == "smalltalk" else OUT_OF_SCOPE_REPLY
        return {"answer": plan.direct_reply or default, "sources": []}

    # ---- specialist: document researcher ----------------------------------------
    def researcher(state: AgentState) -> dict:
        step = state["plan"].steps[state["step_index"]]
        trace = list(state.get("trace", []))
        query, kept, seen = step.task, [], set()
        for attempt in range(settings.max_retrieval_retries + 1):
            started = time.perf_counter()
            chunks = retrieve(query, sources=state.get("scope"))
            trace = _trace({"trace": trace}, "researcher", "search",
                           f"Searched for “{query}” → {len(chunks)} passages", started)
            if not chunks:
                break
            started = time.perf_counter()
            passages = "\n\n".join(
                f"[{i}] ({c.document.metadata['source']})\n{c.document.page_content.partition(chr(10))[2][:1200]}"
                for i, c in enumerate(chunks, 1)
            )
            try:
                grade: Grade = _call(models.fast.with_structured_output(Grade).invoke,
                                     prompts.GRADER.format(task=step.task, passages=passages))
            except Exception as exc:  # noqa: BLE001 - keep everything if grading is unavailable
                report(exc, "grading passages", log)
                grade = Grade(relevant=list(range(1, len(chunks) + 1)), sufficient=True)
            relevant = [chunks[i - 1] for i in grade.relevant if 1 <= i <= len(chunks)]
            for chunk in relevant:
                if chunk.document.metadata["chunk_id"] not in seen:
                    seen.add(chunk.document.metadata["chunk_id"])
                    kept.append(chunk)
            verdict = "enough to answer" if grade.sufficient else "not enough yet"
            trace = _trace({"trace": trace}, "researcher", "grade",
                           f"{len(relevant)} of {len(chunks)} passages relevant, {verdict}", started)
            if grade.sufficient or not grade.better_query or attempt == settings.max_retrieval_retries:
                break
            query = grade.better_query
            trace = _trace({"trace": trace}, "researcher", "rewrite", f"Trying a better search: “{query}”",
                           time.perf_counter())
        finding: Finding = {"agent": "researcher", "task": step.task, "chunks": kept, "ok": bool(kept),
                            "summary": f"{len(kept)} relevant passages"}
        return {"findings": [*state.get("findings", []), finding], "step_index": state["step_index"] + 1,
                "trace": trace}

    # ---- specialist: data analyst (tool-calling agent) ----------------------------
    def analyst(state: AgentState) -> dict:
        step = state["plan"].steps[state["step_index"]]
        started = time.perf_counter()
        query_log: list[dict] = []
        context = "\n".join(
            f"- {c.document.page_content.partition(chr(10))[2][:600]}"
            for f in state.get("findings", []) if f["agent"] == "researcher" for c in f.get("chunks", [])[:3]
        ) or "(none)"
        agent = create_agent(models.strong, make_sql_tools(tables, state.get("scope"), query_log),
                             system_prompt=prompts.ANALYST.format(today=date.today().isoformat()))
        try:
            result = agent.invoke(
                {"messages": [HumanMessage(prompts.ANALYST_TASK.format(task=step.task, context=context))]},
                config={"recursion_limit": settings.agent_recursion_limit},
            )
            summary = result["messages"][-1].text.strip()
        except Exception as exc:  # noqa: BLE001 - the writer can still use other findings
            error = report(exc, "data analysis", log)
            summary = f"Analysis failed: {error.user_message}"
        trace = list(state.get("trace", []))
        for q in query_log:
            outcome = f"error: {q['error']}" if q.get("error") else f"{len(q['rows'])} row(s)"
            trace = _trace({"trace": trace}, "analyst", "sql", f"{q['sql']} → {outcome}", started)
        trace = _trace({"trace": trace}, "analyst", "summary", summary[:300], started)
        finding: Finding = {"agent": "analyst", "task": step.task, "queries": query_log, "summary": summary,
                            "ok": any(not q.get("error") for q in query_log)}
        return {"findings": [*state.get("findings", []), finding], "step_index": state["step_index"] + 1,
                "trace": trace}

    # ---- writer / reviewer / finalize ---------------------------------------------------
    def writer(state: AgentState) -> dict:
        started = time.perf_counter()
        sources = build_sources(state.get("findings", []))
        feedback = ""
        review = state.get("review")
        if review is not None:
            feedback = prompts.WRITER_FEEDBACK.format(feedback=review.feedback or "(none)",
                                                      claims="; ".join(review.unsupported_claims) or "(none)")
        note = ""
        try:
            answer = _call(generate_answer, models.strong, state["plan"].standalone_question, sources, feedback)
        except Exception as exc:  # noqa: BLE001 - overloaded strong model: fall back to the fast one
            if not classify_exception(exc).transient:
                raise
            report(exc, "writer (strong model), falling back to fast model", log)
            answer = _call(generate_answer, models.fast, state["plan"].standalone_question, sources, feedback)
            note = " (strong model unavailable, used fast model)"
        answer, cited = clean_citations(answer, sources)
        attempt = state.get("write_attempts", 0) + 1
        detail = f"Wrote answer from {len(sources)} sources, cited {', '.join(cited) or 'none'}{note}"
        if attempt > 1:
            detail += f" (revision {attempt - 1})"
        return {"answer": answer, "sources": sources, "write_attempts": attempt,
                "trace": _trace(state, "writer", "write", detail, started)}

    def reviewer(state: AgentState) -> dict:
        started = time.perf_counter()
        if not state.get("sources") or state["answer"] == NOT_FOUND:
            review = Review(grounded=True, answers_question=True)
            return {"review": review, "trace": _trace(state, "reviewer", "review", "Nothing to verify", started)}
        prompt = prompts.REVIEWER.format(question=state["plan"].standalone_question,
                                         sources=format_sources(state["sources"]), answer=state["answer"])
        try:
            review: Review = _call(models.fast.with_structured_output(Review).invoke, prompt)
            detail = "Approved" if review.grounded and review.answers_question else f"Rejected: {review.feedback}"
        except Exception as exc:  # noqa: BLE001 - answer is still shown, with a caveat
            report(exc, "reviewing answer", log)
            review, detail = None, "Review unavailable"
        return {"review": review, "trace": _trace(state, "reviewer", "review", detail, started)}

    def after_review(state: AgentState) -> str:
        review = state.get("review")
        rejected = review is not None and not (review.grounded and review.answers_question)
        if rejected and state.get("write_attempts", 0) <= settings.max_answer_retries:
            return "writer"
        return "finalize"

    def finalize(state: AgentState) -> dict:
        answer = redact_secrets(state.get("answer", ""))
        caveat = None
        review = state.get("review")
        sources = state.get("sources", [])
        if state["plan"].intent == "answer" and sources and answer != NOT_FOUND:
            _, cited = clean_citations(answer, sources)
            if review is None:
                caveat = UNVERIFIED
            elif not (review.grounded and review.answers_question):
                caveat = UNSUPPORTED
            elif not cited:
                caveat = NO_CITATIONS
        return {"answer": answer, "caveat": caveat}

    graph = StateGraph(AgentState)
    for name, node in (("supervisor", supervisor), ("direct", direct), ("researcher", researcher),
                       ("analyst", analyst), ("writer", writer), ("reviewer", reviewer), ("finalize", finalize)):
        graph.add_node(name, node)
    routes = {"direct": "direct", "researcher": "researcher", "analyst": "analyst", "writer": "writer"}
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", next_step, routes)
    graph.add_conditional_edges("researcher", next_step, routes)
    graph.add_conditional_edges("analyst", next_step, routes)
    graph.add_edge("direct", "finalize")
    graph.add_edge("writer", "reviewer")
    graph.add_conditional_edges("reviewer", after_review, {"writer": "writer", "finalize": "finalize"})
    graph.add_edge("finalize", END)
    return graph.compile()


def run_agents(question: str, history: list[dict] | None = None, scope: list[str] | None = None,
               models: Models | None = None, tables: TableStore | None = None) -> AgentResult:
    settings = get_settings()
    graph = build_graph(models or default_models(), tables or get_table_store())
    state = graph.invoke(
        {"question": question, "history": history or [], "scope": scope, "trace": []},
        config={"recursion_limit": settings.agent_recursion_limit},
    )
    sources = state.get("sources", [])
    _, cited = clean_citations(state.get("answer", ""), sources)
    plan = state.get("plan")
    return AgentResult(
        intent=plan.intent if plan else "answer",
        question=plan.standalone_question if plan else question,
        answer=state.get("answer", ""),
        sources=sources,
        cited=cited,
        plan=plan,
        review=state.get("review"),
        caveat=state.get("caveat"),
        trace=state.get("trace", []),
    )
