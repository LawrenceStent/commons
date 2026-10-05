"""Keys for outside services, from the environment or a git-ignored `.env` file (see .env.example). Variables already
set in the environment win. Values are never logged or printed: `missing` names what isn't set, nothing more."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = (s.strip() for s in line.split("=", 1))
            if key and value and key not in os.environ:
                os.environ[key] = value


def get(name: str) -> str | None:
    return os.environ.get(name) or None


def missing(*names: str) -> list[str]:
    return [n for n in names if not get(n)]
