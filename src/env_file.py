"""Read and update the project's `.env` file (API keys set from the Settings page).

Only `KEY=value` lines are touched; comments and other lines are preserved.
Values are written without quotes, and the process environment is updated so
the change applies immediately.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from src.config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def set_env_value(key: str, value: str, path: Path = ENV_PATH) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(f"Invalid environment variable name: {key!r}")
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise ValueError("Value must be a single line")
    lines = path.read_text().splitlines() if path.exists() else []
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)  # keys are secrets; keep the file private to the user
    except OSError:
        pass
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
