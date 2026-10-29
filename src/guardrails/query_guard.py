"""Question guardrail: runs before any model sees the user's question.

- Blocks attempts to override the assistant's instructions or extract its
  prompt ("ignore previous instructions", "reveal your system prompt").
  Text inside quotes is ignored, so a SecOps analyst can still ask
  'what does "ignore previous instructions" mean?'.
- Masks secrets typed into a question before they reach the LLM or the logs.
- Enforces a length limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.guardrails.content_scan import INJECTION_PATTERNS, redact_secrets

MAX_QUESTION_CHARS = 2000

_EXTRACTION_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(reveal|show|print|repeat|output|tell me)\b.{0,30}\b(system|hidden|initial|original)\s+(prompt|instructions?|message)",
        r"\b(your|the)\s+(system|hidden)\s+prompt\b",
        r"\bpretend (you are|to be)\b",
        r"\bact as (an? )?(unrestricted|unfiltered|jailbroken)\b",
    )
)
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']{4,}'|`[^`]*`")

BLOCKED_REPLY = (
    "I can't follow instructions that try to change how I work. "
    "Ask me a question about your IT, security or operations documents instead."
)


@dataclass
class QueryCheck:
    allowed: bool
    question: str
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def check_question(text: str) -> QueryCheck:
    question = " ".join((text or "").split())
    if not question:
        return QueryCheck(False, question, "empty")
    if len(question) > MAX_QUESTION_CHARS:
        return QueryCheck(False, question[:MAX_QUESTION_CHARS], "too_long")

    unquoted = _QUOTED.sub(" ", question)
    for pattern in (*INJECTION_PATTERNS, *_EXTRACTION_PATTERNS):
        if pattern.search(unquoted):
            return QueryCheck(False, question, "instruction_override")

    notes = []
    masked = redact_secrets(question)
    if masked != question:
        notes.append("Your question contained a password or key; it was hidden before processing.")
    return QueryCheck(True, masked, notes=notes)
