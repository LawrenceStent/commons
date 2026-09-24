"""One directory per community. Paths may not escape it."""

from __future__ import annotations

from pathlib import Path


class WorkspaceEscape(Exception):
    pass


class Workspace:
    def __init__(self, root: Path, community: str):
        self.root = (Path(root) / community).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise WorkspaceEscape(rel)
        return p

    def write(self, rel: str, text: str) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def read(self, rel: str) -> str:
        return self.path(rel).read_text()
