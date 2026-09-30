"""The archive: a society's large reference material, searched on demand rather than sent on every call.

Anything too big for a steward's prompt (reports, datasets written up as text, prior research, notes) goes in a
society's `archive/` folder as .md or .txt files. It is split into passages of about 800 characters; stewards
search it with `search_archive(query)` (keyword ranking, no model call) and read one passage in full with
`read_archive(passage_id)`. Both tools are free: the only cost is the tokens of what the steward chooses to read.

The archive is written by you, so its text is trusted reference material, but it is still shown as reference,
never as instructions.

Work cites a passage as `[archive: <id>]`. Citations are checked by rule before any grading: work that cites a
passage that doesn't exist fails that part (see World._try_grade).
"""

from __future__ import annotations

import math
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PASSAGE = 800  # characters, roughly
MAX_RESULTS = 5
_WORD = re.compile(r"[a-z0-9]+")
_CITE = re.compile(r"\[archive:\s*([A-Za-z0-9-]+#\d+)\s*\]")
_STOP = frozenset("the a an and or of to in on for with is are be it this that as at by from was were not".split())


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _stem(rel: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", Path(rel).with_suffix("").as_posix().lower()).strip("-")


def citations(text: str) -> list[str]:
    """The archive passages a piece of work cites, in order, without repeats."""
    return list(dict.fromkeys(m.lower() for m in _CITE.findall(text)))


@dataclass(frozen=True)
class Passage:
    id: str  # "<file stem>#<n>"
    source: str
    text: str


class Archive:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else None
        self.passages: dict[str, Passage] = {}
        self._tf: dict[str, Counter] = {}
        self._df: Counter = Counter()
        if self.root and self.root.exists():
            for path in sorted(self.root.rglob("*")):
                if path.is_file() and path.suffix.lower() in (".md", ".txt"):
                    self._add(path)

    def _add(self, path: Path) -> None:
        self._index(str(path.relative_to(self.root)), path.read_text(errors="replace"))

    def _index(self, rel: str, text: str) -> list[str]:
        chunks, current = [], ""
        for para in re.split(r"\n\s*\n", text):
            if current and len(current) + len(para) > PASSAGE:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{para}".strip()
            while len(current) > 2 * PASSAGE:  # one huge paragraph: cut it
                chunks.append(current[:PASSAGE])
                current = current[PASSAGE:]
        if current:
            chunks.append(current)
        stem = _stem(rel)
        ids = []
        for n, chunk in enumerate(chunks, 1):
            p = Passage(f"{stem}#{n}", rel, chunk)
            if p.id in self.passages:  # re-indexing the same source: replace its terms
                self._df.subtract(self._tf[p.id].keys())
            self.passages[p.id] = p
            tf = Counter(_terms(chunk))
            self._tf[p.id] = tf
            self._df.update(tf.keys())
            ids.append(p.id)
        return ids

    def add_page(self, url: str, title: str, text: str, fetched: str = "") -> list[str]:
        """A page read from the web joins the archive (and, if the archive has a folder, is kept in archive/web/ for
        later runs). Returns its passage ids; a page already here isn't indexed twice."""
        parts = urllib.parse.urlsplit(url)
        slug = re.sub(r"[^a-z0-9]+", "-", f"{parts.hostname or ''}{parts.path}".lower()).strip("-")[:80]
        rel = f"web/{slug}.md"
        existing = sorted((p.id for p in self.passages.values() if p.source == rel), key=lambda i: int(i.rsplit("#", 1)[1]))
        if existing:
            return existing
        body = f"# {title.strip()[:200]}\n\nSource: {url}{f' (read {fetched})' if fetched else ''}\n\n{text.strip()}"
        if self.root:
            (self.root / "web").mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(body)
        return self._index(rel, body)

    def __len__(self) -> int:
        return len(self.passages)

    def search(self, query: str, k: int = MAX_RESULTS) -> list[tuple[Passage, float]]:
        """Passages ranked by a simple BM25 score: deterministic, instant, no model call."""
        q = _terms(query)
        if not q or not self.passages:
            return []
        n = len(self.passages)
        avg = sum(sum(tf.values()) for tf in self._tf.values()) / n
        scored = []
        for pid, tf in self._tf.items():
            length, score = sum(tf.values()), 0.0
            for t in q:
                if tf[t]:
                    idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                    score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * length / avg))
            if score > 0:
                scored.append((self.passages[pid], round(score, 3)))
        return sorted(scored, key=lambda x: (-x[1], x[0].id))[:k]

    def get(self, passage_id: str) -> Passage | None:
        return self.passages.get(passage_id)
