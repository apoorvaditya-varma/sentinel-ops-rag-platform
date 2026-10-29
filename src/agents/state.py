"""Shared state passed between the agents in the LangGraph workflow."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    agent: str = Field(description="Specialist key from the menu, e.g. researcher or analyst")
    task: str = Field(description="Precise instruction for that specialist")


class Plan(BaseModel):
    intent: Literal["answer", "smalltalk", "out_of_scope"] = Field(
        description="answer = needs the documents; smalltalk = greeting/thanks; out_of_scope = unrelated to IT/security/ops"
    )
    standalone_question: str = Field(description="The question rewritten to be understandable without the chat history")
    steps: list[PlanStep] = Field(default_factory=list, max_length=3,
                                  description="Ordered specialist steps (empty unless intent is answer)")
    direct_reply: str | None = Field(default=None, description="Short reply for smalltalk / out_of_scope")


class Grade(BaseModel):
    relevant: list[int] = Field(default_factory=list, description="Numbers of the passages that help answer the task")
    sufficient: bool = Field(description="True if the relevant passages are enough to complete the task")
    better_query: str | None = Field(default=None, description="If not sufficient: a better search query")


class Review(BaseModel):
    grounded: bool = Field(description="True if every factual claim is supported by the cited sources")
    answers_question: bool = Field(description="True if the answer addresses the question")
    unsupported_claims: list[str] = Field(default_factory=list)
    feedback: str = Field(default="", description="What the writer must fix, if anything")


class Finding(TypedDict, total=False):
    agent: str
    task: str
    chunks: list[Any]          # RetrievedChunk (researcher)
    queries: list[dict]        # {"sql", "columns", "rows", "markdown", "error"} (analyst)
    summary: str
    ok: bool


class TraceStep(TypedDict):
    agent: str
    action: str
    detail: str
    ms: int


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict]          # previous turns: {"role", "content"}
    scope: list[str] | None      # restrict to these source files
    plan: Plan
    step_index: int
    findings: list[Finding]
    answer: str
    sources: list[dict]          # numbered sources the writer saw: {"label", "kind", ...}
    review: Review | None
    write_attempts: int
    caveat: str | None
    direct_reply: str | None
    trace: list[TraceStep]
