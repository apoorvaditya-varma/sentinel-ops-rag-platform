"""Content guardrails shared by ingestion and answer generation.

- Secret detection / redaction: ops documents routinely contain keys and
  passwords; they are masked before indexing and before display.
- Prompt-injection detection (OWASP LLM01, indirect injection): instructions
  hidden in uploaded documents are flagged so chunks can be tagged untrusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z]+ )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "connection_string": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]{3,}@[^\s]+"),
    "password_assignment": re.compile(
        # Value must look like a credential (8+ chars with a digit/symbol), not prose like "secret: confirm".
        r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]?(?!\[REDACTED_)"
        r"(?=[^\s'\"]*[\d!@#$%^&*_+/=-])[^\s'\"]{8,}"
    ),
}

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|all)\b.{0,20}\b(instructions|rules|prompts?)\b",
        r"\byou are now\b",
        r"\b(system|developer)\s*(prompt|message|mode)\b",
        r"<!--\s*(system|assistant|instruction)",
        r"\bdo not (mention|reveal|tell)\b.{0,40}\b(user|this)\b",
        r"\b(jailbreak|DAN mode)\b",
        r"\bnew instructions?\s*:",
    )
)


@dataclass
class ScanReport:
    secrets: dict[str, int] = field(default_factory=dict)
    injection_snippets: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        notes = []
        if self.secrets:
            found = ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in self.secrets.items())
            notes.append(f"Possible secrets found ({found}); they will be masked before indexing.")
        if self.injection_snippets:
            notes.append(
                f"{len(self.injection_snippets)} possible prompt-injection passage(s); "
                "they will be indexed as untrusted text."
            )
        return notes


def scan_text(text: str) -> ScanReport:
    report = ScanReport()
    for kind, pattern in SECRET_PATTERNS.items():
        count = len(pattern.findall(text))
        if count:
            report.secrets[kind] = count
    # Several patterns often hit the same hidden instruction: merge nearby matches into one passage.
    spans = sorted((m.start(), m.end()) for pattern in INJECTION_PATTERNS for m in pattern.finditer(text))
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1] + 200:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    report.injection_snippets = [
        text[max(0, start - 40) : end + 40].replace("\n", " ") for start, end in merged
    ]
    return report


def redact_secrets(text: str) -> str:
    for kind, pattern in SECRET_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{kind.upper()}]", text)
    return text
