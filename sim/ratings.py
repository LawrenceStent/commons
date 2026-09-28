"""Your ratings: the human sample that anchors a society's scorecard.

A grader can only say whether work meets its rubric. Whether it is *useful* is yours to say, and you can't read
everything, so the world sets aside a sample of the paid work for you:

    samples.jsonl   written by the world: every `every`-th paid job, with its parts in full, under an id that
                    names the run ("live-lmstudio-20260928-1200/J12"), since every run numbers its jobs from 1
    ratings.jsonl   written by you (with `python -m sim.rate SOCIETY`, or by hand): one line per rating,
                    {"id": "<run>/J12", "rating": 2, "note": "..."}

Ratings: 0 wrong or harmful · 1 not useful · 2 useful · 3 very useful.

A running world re-reads ratings.jsonl every cycle and applies ratings of its own run's work. A rating counts on the scorecard ("useful", "harmful", "cost per
useful") and as first-hand evidence about whoever did each part, from an observer called "operator": a 0 hurts
their standing, a 2 or 3 helps it. Rating is optional; without it the scorecard's "you" rows say "no data".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SCALE = {0: "wrong or harmful", 1: "not useful", 2: "useful", 3: "very useful"}
EVIDENCE = {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.0}  # what a rating says about the work, as a reputation outcome


@dataclass(frozen=True)
class Rating:
    id: str  # "<run>/<job>"
    rating: int
    note: str = ""


class Ratings:
    def __init__(self, folder: str | Path | None, run: str = "run", every: int = 3):
        self.folder = Path(folder) if folder else None
        self.run = run
        self.every = max(1, every)
        self.ratings: dict[str, Rating] = {}  # this run's, by sample id
        self.samples: dict[str, dict] = {}  # this run's samples by id (who did what), for applying ratings
        self.errors: list[str] = []
        self._paid = 0
        self._offset = 0  # bytes of ratings.jsonl already read
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)

    def sample(self, record: dict) -> bool:
        """Offer every `every`-th paid job for rating. Deterministic, so the same run samples the same jobs."""
        self._paid += 1
        if not self.folder or (self._paid - 1) % self.every:
            return False
        record = {"id": f"{self.run}/{record['job']}", **record}
        self.samples[record["id"]] = record
        with open(self.folder / "samples.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")
        return True

    def reload(self) -> list[Rating]:
        """New ratings since the last read. A later rating of the same job replaces the earlier one."""
        path = self.folder / "ratings.jsonl" if self.folder else None
        if not path or not path.exists():
            return []
        with open(path) as f:
            f.seek(self._offset)
            text = f.read()
        complete = text[: text.rfind("\n") + 1]  # a line still being written waits for the next cycle
        self._offset += len(complete.encode())
        new = []
        for line in complete.splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                r = Rating(str(d["id"]), int(d["rating"]), str(d.get("note", ""))[:300])
                if r.rating not in SCALE:
                    raise ValueError(f"rating must be one of {sorted(SCALE)}")
            except (ValueError, KeyError, TypeError) as e:
                self.errors.append(f"ratings.jsonl: {e}: {line[:80]}")
                continue
            if r.id in self.samples:  # another run's work is rated for that run's record, not this one
                self.ratings[r.id] = r
                new.append(r)
        return new


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def unrated(folder: Path) -> list[dict]:
    done = {d.get("id") for d in _read_jsonl(folder / "ratings.jsonl")}
    return [s for s in _read_jsonl(folder / "samples.jsonl") if s["id"] not in done]


def add(folder: Path, sample_id: str, rating: int, note: str = "") -> None:
    if rating not in SCALE:
        raise ValueError(f"rating must be one of {sorted(SCALE)}")
    with open(folder / "ratings.jsonl", "a") as f:
        f.write(json.dumps({"id": sample_id, "rating": rating, "note": note}) + "\n")
