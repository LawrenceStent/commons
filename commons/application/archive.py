"""The archive: a society's large reference material, searched on demand rather than sent on every call.

Anything too big for a steward's prompt (reports, datasets written up as text, prior research, notes) goes in a
society's `archive/` folder as .md or .txt files. It is split into passages of about 800 characters; stewards
search it with `search_archive(query)` (keyword ranking, no model call) and read one passage in full with
`read_archive(passage_ids)` (up to 5 at once). Both tools are free: the only cost is the tokens of what the steward chooses to read.

The archive is written by you, so its text is trusted reference material, but it is still shown as reference,
never as instructions.
"""

from __future__ import annotations

from pathlib import Path

from commons.domain.archive import ArchiveIndex


class Archive(ArchiveIndex):
    """An archive fed from a society's `archive/` folder (.md and .txt files); pages read from the web are kept in its
    `web/` subfolder, so later runs have them too."""

    def __init__(self, root: str | Path | None = None):
        super().__init__()
        self.root = Path(root) if root else None
        if self.root and self.root.exists():
            for path in sorted(self.root.rglob("*")):
                if path.is_file() and path.suffix.lower() in (".md", ".txt"):
                    self._index(str(path.relative_to(self.root)), path.read_text(errors="replace"))

    def _keep(self, rel: str, body: str) -> None:
        if self.root:
            (self.root / "web").mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(body)
