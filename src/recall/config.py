"""Credential and backend resolution.

Keys are read from the process environment first, then from a project-local
`.env` (gitignored). No key is ever written to a tracked file.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

_loaded = False


def load_env(path: Path | None = None) -> None:
    """Populate os.environ from a KEY=value file, without overwriting."""
    global _loaded
    path = path or ENV_FILE
    if _loaded or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)
    _loaded = True


def get_key(name: str) -> str | None:
    load_env()
    value = os.environ.get(name)
    return value or None


def backend_name() -> str:
    """Which grader backend to use. `anthropic` unless told otherwise."""
    load_env()
    return os.environ.get("RECALL_BACKEND", "anthropic").strip().lower()


def model_override() -> str | None:
    load_env()
    return os.environ.get("RECALL_MODEL") or None
