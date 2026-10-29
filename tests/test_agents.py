"""Multi-agent workflow tests with scripted models over the real (temporary) index and DuckDB."""

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents import graph as graph_module
from src.agents.graph import NO_CITATIONS, OUT_OF_SCOPE_REPLY, UNSUPPORTED, UNVERIFIED, Models, run_agents
from src.config import get_settings, sample_documents
from src.ingestion import pipeline
from src.rag.chain import NOT_FOUND
from src.retrieval import retriever
from src.tables.sql_store import TableStore
from src.vectorstore.store import KnowledgeStore
from tests.fakes import ScriptedChatModel, norm, passages, prompt_text, tool_call

SAMPLES = get_settings().sample_docs_dir
SCAN = "vulnerability_scan_2026q3__findings"


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    root = tmp_path_factory.mktemp("agents")
    store = KnowledgeStore(root / "qdrant", "test")
    tables = TableStore(root / "tables.duckdb")
    settings = replace(get_settings(), upload_dir=root / "uploads")
    settings.upload_dir.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "get_store", lambda: store)
        mp.setattr(pipeline, "get_table_store", lambda: tables)
        mp.setattr(pipeline, "get_settings", lambda: settings)
        mp.setattr(retriever, "get_store", lambda: store)
        for path in sample_documents():
            pipeline.ingest_file(path)
        yield store, tables
    store.client.close()
    tables.close()


def plan(*steps, intent="answer", question="q", reply=None):
    return {"intent": intent, "standalone_question": question, "direct_reply": reply,
            "steps": [{"agent": agent, "task": task} for agent, task in steps]}


def fast_model(plan_args, grade=None, review=None):
    """Fast model: supervisor plan, grader (default: passages containing the plan's key phrase), reviewer."""
    reviews = iter(review or [])

    def respond(messages, tools):
        if "Plan" in tools:
            return tool_call("Plan", plan_args)
        if "Grade" in tools:
            return tool_call("Grade", grade(messages) if grade else {"relevant": [1, 2], "sufficient": True})
        if "Review" in tools:
            return tool_call("Review", next(reviews, {"grounded": True, "answers_question": True}))
        raise AssertionError(f"unexpected fast-model call: {tools}")

    return ScriptedChatModel(responder=respond)


def grade_containing(phrase):
    def grade(messages):
        relevant = [i for i, text in passages(messages).items() if norm(phrase) in norm(text)]
        return {"relevant": relevant, "sufficient": bool(relevant)}
    return grade


def writer_model(answers, analyst=None):
    """Strong model: analyst tool loop (when SQL tools are bound) and the answer writer."""
    answers = iter(answers)

    def respond(messages, tools):
        if "run_sql" in tools:
            return analyst(messages)
        return AIMessage(content=next(answers))

    return ScriptedChatModel(responder=respond)


def sql_analyst(sql, summary="Done."):
    """Scripted ReAct loop: list_tables -> describe_table -> run_sql -> final summary."""
    def respond(messages):
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        if len(tool_results) == 0:
            return tool_call("list_tables", {})
        if len(tool_results) == 1:
            return tool_call("describe_table", {"table": SCAN})
        if len(tool_results) == 2:
            return tool_call("run_sql", {"sql": sql})
        return AIMessage(content=summary)
    return respond


# ---- researcher + writer + reviewer --------------------------------------------
def test_document_question_end_to_end(stores):
    fast = fast_model(plan(("researcher", "Find the remediation SLA for critical vulnerabilities on internet-facing systems"),
                           question="What is the patch SLA for critical internet-facing vulnerabilities?"),
                      grade=grade_containing("72 hours"))
    strong = writer_model(["Critical vulnerabilities on internet-facing systems must be fixed within 72 hours [S1]. "
                           "See also [S9]."])
    result = run_agents("patch SLA internet facing critical?", models=Models(strong, fast), tables=stores[1])

    assert "72 hours" in result.answer and "[S1]" in result.answer and "[S9]" not in result.answer
    assert result.cited == ["S1"] and result.caveat is None
    assert result.sources[0]["header"].startswith("information_security_policy.pdf")
    assert result.agents_used == ["researcher"]
    assert [(t["agent"], t["action"]) for t in result.trace] == [
        ("supervisor", "plan"), ("researcher", "search"), ("researcher", "grade"),
        ("writer", "write"), ("reviewer", "review")]
    writer_prompt = prompt_text(strong.calls[0]["messages"])
    assert '<source id="S1"' in writer_prompt and "untrusted" in writer_prompt


def test_researcher_rewrites_query_when_evidence_missing(stores):
    attempts = iter([
        {"relevant": [], "sufficient": False, "better_query": "revoke leaked AWS access key CloudTrail"},
        None,
    ])

    def grade(messages):
        scripted = next(attempts)
        return scripted or grade_containing("CloudTrail")(messages)

    fast = fast_model(plan(("researcher", "What to do after a key leak")), grade=grade)
    result = run_agents("key leak?", models=Models(writer_model(["Revoke it and check CloudTrail [S1]."]), fast),
                        tables=stores[1])
    actions = [t["action"] for t in result.trace if t["agent"] == "researcher"]
    assert actions == ["search", "grade", "rewrite", "search", "grade"]
    assert "CloudTrail" in result.sources[0]["text"]


def test_research_retries_are_bounded(stores):
    fast = fast_model(plan(("researcher", "x")),
                      grade=lambda m: {"relevant": [], "sufficient": False, "better_query": "another try"})
    result = run_agents("x", models=Models(writer_model(["unused"]), fast), tables=stores[1])
    searches = [t for t in result.trace if t["action"] == "search"]
    assert len(searches) == get_settings().max_retrieval_retries + 1
    assert result.answer == NOT_FOUND and result.sources == []


# ---- analyst (tool-calling agent) ---------------------------------------------------
def test_analyst_queries_tables_with_tools(stores):
    sql = f"SELECT owner_team, COUNT(*) AS n FROM {SCAN} WHERE status = 'Open' AND severity = 'Critical' GROUP BY 1 ORDER BY 2 DESC, 1"
    expected = stores[1].run_query(sql).rows
    fast = fast_model(plan(("analyst", "Count open critical findings per owner team")))
    strong = writer_model([f"{expected[0][0]} has the most open critical findings ({expected[0][1]}) [T1]."],
                          analyst=sql_analyst(sql, "Counted open criticals per team."))
    result = run_agents("open criticals per team?", models=Models(strong, fast), tables=stores[1])

    query_sources = [s for s in result.sources if s["kind"] == "query"]
    assert query_sources[0]["label"] == "T1" and query_sources[0]["sql"] == sql
    assert [tuple(r) for r in query_sources[0]["query"]["rows"]] == [tuple(r) for r in expected]
    assert result.cited == ["T1"] and result.agents_used == ["analyst"]
    assert any(t["action"] == "sql" and "row(s)" in t["detail"] for t in result.trace)
    tool_names = {name for call in strong.calls_with("run_sql") for name in call["tools"]}
    assert tool_names == {"list_tables", "describe_table", "run_sql"}


def test_analyst_date_columns_are_json_safe(stores):
    """Regression: SLA/first_seen dates from the scan table crashed history storage (TypeError on json.dumps)."""
    import json

    sql = f"SELECT finding_id, sla_due, first_seen FROM {SCAN} WHERE status = 'Open' ORDER BY sla_due LIMIT 3"
    fast = fast_model(plan(("analyst", "List the earliest open SLA due dates")))
    strong = writer_model(["The earliest due date is shown [T1]."], analyst=sql_analyst(sql))
    result = run_agents("earliest due dates?", models=Models(strong, fast), tables=stores[1])
    query = next(s for s in result.sources if s["kind"] == "query")["query"]
    assert all(isinstance(row[1], str) and row[1].startswith("2026-") for row in query["rows"])
    json.dumps(query)  # must not raise


def test_analyst_sql_errors_are_returned_to_the_agent(stores):
    bad = iter(["DROP TABLE x", f"SELECT COUNT(*) FROM {SCAN}"])
    seen_errors = []

    def analyst(messages):
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if results and "ERROR" in results[-1].text:
            seen_errors.append(results[-1].text)
        if len(results) < 2:
            return tool_call("run_sql", {"sql": next(bad)})
        return AIMessage(content="There are 48 findings.")

    fast = fast_model(plan(("analyst", "How many findings?")))
    result = run_agents("how many findings", models=Models(writer_model(["48 findings [T1]."], analyst), fast),
                        tables=stores[1])
    assert "Only SELECT" in seen_errors[0]
    assert [s["label"] for s in result.sources] == ["T1"]  # failed query is not a citable source


def test_researcher_then_analyst_collaborate(stores):
    sql = f"SELECT COUNT(*) FROM {SCAN} WHERE severity = 'Critical' AND status = 'Open' AND sla_due < DATE '2026-10-01'"
    fast = fast_model(plan(("researcher", "Find the remediation SLA for critical vulnerabilities"),
                           ("analyst", "Count open critical findings past their SLA")),
                      grade=grade_containing("7 calendar days"))
    strong = writer_model(["Critical findings must be fixed in 7 days [S1]; several are overdue [T1]."],
                          analyst=sql_analyst(sql))
    result = run_agents("overdue criticals vs policy?", models=Models(strong, fast), tables=stores[1])

    analyst_task = prompt_text(strong.calls_with("run_sql")[0]["messages"])
    assert "Context from earlier specialists" in analyst_task and "7 calendar days" in analyst_task
    assert result.agents_used == ["researcher", "analyst"] and result.cited == ["S1", "T1"]


# ---- supervisor decisions ----------------------------------------------------------
@pytest.mark.parametrize("intent, reply, expected", [
    ("smalltalk", "Hi! Ask me about your runbooks.", "Hi! Ask me about your runbooks."),
    ("out_of_scope", None, OUT_OF_SCOPE_REPLY),
])
def test_direct_replies_skip_specialists(stores, monkeypatch, intent, reply, expected):
    monkeypatch.setattr(graph_module, "retrieve", lambda *a, **k: pytest.fail("should not search"))
    fast = fast_model(plan(intent=intent, reply=reply))
    result = run_agents("hello", models=Models(writer_model([]), fast), tables=stores[1])
    assert result.answer == expected and result.sources == [] and result.intent == intent


def test_unknown_specialists_and_unavailable_analyst_are_dropped(stores):
    fast = fast_model(plan(("hacker", "do evil"), ("analyst", "count rows")), grade=grade_containing("MFA"))
    result = run_agents("MFA rules", scope=["information_security_policy.pdf"],  # no tables in scope
                        models=Models(writer_model(["Admins need hardware-key MFA [S1]."]), fast), tables=stores[1])
    assert [s.agent for s in result.plan.steps] == ["researcher"]


def test_follow_up_uses_history(stores):
    fast = fast_model(plan(("researcher", "x"), question="What is the SLA for high severity vulnerabilities?"),
                      grade=grade_containing("30 calendar days"))
    history = [{"role": "user", "content": "What is the SLA for critical vulnerabilities?"},
               {"role": "assistant", "content": "7 days [S1]."}]
    run_agents("and for high?", history=history, models=Models(writer_model(["30 days [S1]."]), fast), tables=stores[1])
    supervisor_prompt = prompt_text(fast.calls_with("Plan")[0]["messages"])
    assert "user: What is the SLA for critical vulnerabilities?" in supervisor_prompt


# ---- reviewer, output guard, degradation -----------------------------------------
def test_reviewer_sends_answer_back_once(stores):
    fast = fast_model(plan(("researcher", "MFA for admins")), grade=grade_containing("MFA"),
                      review=[{"grounded": False, "answers_question": True, "unsupported_claims": ["SMS is fine"],
                               "feedback": "Remove the SMS claim"}])
    strong = writer_model(["Admins may use SMS codes [S1].", "Admins must use FIDO2 hardware keys [S1]."])
    result = run_agents("admin MFA?", models=Models(strong, fast), tables=stores[1])
    assert "FIDO2" in result.answer and result.caveat is None
    assert "reviewer rejected" in prompt_text(strong.calls[1]["messages"]).lower()
    assert [t["action"] for t in result.trace].count("write") == 2


def test_persistent_rejection_adds_caveat(stores):
    reject = {"grounded": False, "answers_question": True, "feedback": "unsupported"}
    fast = fast_model(plan(("researcher", "MFA")), grade=grade_containing("MFA"), review=[reject] * 5)
    strong = writer_model(["Answer A [S1].", "Answer B [S1].", "Answer C [S1]."])
    result = run_agents("MFA", models=Models(strong, fast), tables=stores[1])
    assert result.caveat == UNSUPPORTED
    assert len(strong.calls) == 1 + get_settings().max_answer_retries


def test_secrets_masked_and_uncited_answers_flagged(stores):
    fast = fast_model(plan(("researcher", "leaked key")), grade=grade_containing("CloudTrail"))
    strong = writer_model(["The leaked key was AKIAIOSFODNN7EXAMPLE; rotate it."])
    result = run_agents("leaked key", models=Models(strong, fast), tables=stores[1])
    assert "AKIAIOSFODNN7EXAMPLE" not in result.answer and "[REDACTED_AWS_ACCESS_KEY]" in result.answer
    assert result.caveat == NO_CITATIONS


def test_fast_model_outage_degrades_gracefully(stores, monkeypatch):
    monkeypatch.setattr("src.errors.time.sleep", lambda s: None)

    def broken(messages, tools):
        raise TimeoutError("read timed out")

    fast = ScriptedChatModel(responder=broken)
    strong = writer_model(["Hardware-key MFA is required for administrators [S1]."])
    result = run_agents("admin MFA requirements", models=Models(strong, fast), tables=stores[1])
    assert [s.agent for s in result.plan.steps] == ["researcher"]          # default plan
    assert result.caveat == UNVERIFIED and "[S1]" in result.answer        # no review, but still answered
    assert len(fast.calls) >= 3 * get_settings().llm_retry_attempts      # retried plan, grade, review


def test_cancel_event_stops_the_workflow(stores):
    import threading

    from src.errors import CancelledError

    cancel = threading.Event()
    cancel.set()
    fast = fast_model(plan(("researcher", "x")))
    with pytest.raises(CancelledError):
        run_agents("x", models=Models(writer_model(["unused"]), fast), tables=stores[1], cancel=cancel)
    assert fast.calls == []  # nothing was sent to a model


def test_writer_failure_propagates(stores, monkeypatch):
    monkeypatch.setattr("src.errors.time.sleep", lambda s: None)

    def broken(messages, tools):
        raise ValueError("model exploded")

    fast = fast_model(plan(("researcher", "MFA")), grade=grade_containing("MFA"))
    with pytest.raises(ValueError):
        run_agents("MFA", models=Models(ScriptedChatModel(responder=broken), fast), tables=stores[1])
