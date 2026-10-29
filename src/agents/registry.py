"""Capability registry: which specialist agents exist and what each one can do.

The supervisor's planning prompt is generated from this registry, so adding a
specialist means adding an entry here and a runner in `src/agents/graph.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    title: str
    capability: str      # shown to the supervisor when planning
    tools: tuple[str, ...]
    model: str           # "strong" | "fast" | "none"


SUPERVISOR = AgentSpec(
    "supervisor", "Supervisor",
    "Understands the question, rewrites follow-ups into standalone questions, answers greetings directly, "
    "refuses out-of-scope requests and plans which specialists to use.",
    (), "fast",
)

SPECIALISTS: dict[str, AgentSpec] = {
    spec.key: spec
    for spec in (
        AgentSpec(
            "researcher", "Document Researcher",
            "Finds facts in text documents: policies, standards, runbooks, postmortems, incident plans, configs and "
            "logs. Use for 'what/why/how/should' questions, procedures, rules, SLAs and definitions.",
            ("search_documents",), "fast",
        ),
        AgentSpec(
            "analyst", "Data Analyst",
            "Answers questions over tabular data (CSV/Excel) with read-only SQL: counts, totals, filters, top-N, "
            "grouping, dates. Use for 'how many', 'which hosts/teams/alerts', 'list all', trends.",
            ("list_tables", "describe_table", "run_sql"), "strong",
        ),
    )
}

WRITER = AgentSpec(
    "writer", "Answer Writer",
    "Writes the final answer only from the specialists' findings, with [S#]/[T#] citations.",
    (), "strong",
)

REVIEWER = AgentSpec(
    "reviewer", "Reviewer",
    "Checks that every claim in the answer is supported by the cited sources and that the question is answered.",
    (), "fast",
)

ALL_AGENTS = {a.key: a for a in (SUPERVISOR, *SPECIALISTS.values(), WRITER, REVIEWER)}


def specialist_menu() -> str:
    return "\n".join(f"- {s.key}: {s.title}. {s.capability}" for s in SPECIALISTS.values())
