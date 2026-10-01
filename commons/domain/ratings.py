"""A rating: your 0-3 verdict on a sampled piece of work, and what it means as evidence. See application/ratings.py."""

from __future__ import annotations

from dataclasses import dataclass

SCALE = {0: "wrong or harmful", 1: "not useful", 2: "useful", 3: "very useful"}
EVIDENCE = {0: 0.0, 1: 0.4, 2: 0.8, 3: 1.0}  # what a rating says about the work, as a reputation outcome


@dataclass(frozen=True)
class Rating:
    id: str  # "<run>/<job>"
    rating: int
    note: str = ""

