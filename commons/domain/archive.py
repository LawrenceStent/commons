"""The archive's index: reference material split into passages, ranked by keyword (BM25), and the citation format.
Pure: no files. The folder that feeds it is application/archive.py.

Work cites a passage as `[archive: <id>]`. Citations are checked by rule before any grading: work that cites a
passage that doesn't exist fails that part (see the grading service, commons/application/services/grading.py).
"""


from __future__ import annotations

import math
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from commons.domain.ids import PassageId

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


def sources(text: str) -> set[str]:
    """The distinct source files a piece of work cites: three passages of one page are one source."""
    return {c.split("#", 1)[0] for c in citations(text)}


@dataclass(frozen=True)
class Passage:
    id: str  # "<file stem>#<n>"
    source: str
    text: str


class ArchiveIndex:
    """Passages and their search index, in memory. Where the text comes from (a folder, the web) is the caller's
    business; `_keep` is the hook that stores a page read from the web (application/archive.py keeps it on disk)."""

    def __init__(self):
        self.passages: dict[str, Passage] = {}
        self._tf: dict[str, Counter] = {}
        self._df: Counter = Counter()

    def _keep(self, rel: str, body: str) -> None:
        pass

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
        self._keep(rel, body)
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

    def get(self, passage_id: PassageId) -> Passage | None:
        return self.passages.get(passage_id)
