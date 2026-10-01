"""Append-only JSON-lines files: how a running society and the person running it exchange records through a folder
(samples to rate and your ratings; gate requests and your decisions).

One record per line. A reader keeps its byte offset, so each read returns only what was appended since, and a line
still being written (no newline yet) waits for the next read.
"""

from __future__ import annotations

import json
from pathlib import Path


class JsonlLog:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._offset = 0  # bytes already read by read_new

    def append(self, record: dict) -> None:
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\n")

    def read_new(self) -> list[str]:
        """Complete, non-blank lines appended since the last call, unparsed (the caller decides what's valid)."""
        if not self.path or not self.path.exists():
            return []
        with open(self.path) as f:
            f.seek(self._offset)
            text = f.read()
        complete = text[: text.rfind("\n") + 1]
        self._offset += len(complete.encode())
        return [line for line in complete.splitlines() if line.strip()]

    def read_all(self) -> list[dict]:
        """Every record that parses, from the start; lines that don't parse are skipped."""
        if not self.path or not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
