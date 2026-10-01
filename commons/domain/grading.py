"""Grading: what a judgement of one part of a job looks like, and the stub that reads scripted quality.

Scripted policies write artifacts that carry their quality in a tag, `<q=0.83>`, which `StubGrader` reads back;
live runs use an LLM grader (commons/application/graders.py). Here, below `sim`, so scripted strategies and the LLM runtime can use the
tags without importing the world.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from commons.domain.compute import Usage
from commons.domain.money import Micros


@dataclass(frozen=True)
class Grade:
    score: float  # 0..1
    cost: Micros = 0  # micro-units spent grading, charged to the treasury
    reason: str = ""
    # set when a model did the grading
    model: str | None = None  # what answered
    price_as: str | None = None  # the price-table entry it is charged at
    usage: Usage | None = None
    real: bool = False  # someone is billed for this call
    ms: int | None = None
    cache_hit: float | None = None
    # an outcome known only later (a trading P&L, a verified claim): settle this many cycles on. The grader's
    # settle(job) is then asked again and may return new scores {capability: score}, or None to keep these.
    settle_after: int = 0


class Grader(Protocol):
    def grade(self, spec: str, rubric: str, artifact: str) -> Grade: ...


_TAG = re.compile(r"<q=([0-9.]+)>")


def is_tagged(artifact: str | None) -> bool:
    return bool(_TAG.search(artifact or ""))


def strip_tags(text: str) -> str:
    """Model-written work must never carry a scripted quality tag, or the hybrid grader would believe it."""
    return _TAG.sub("", text)


def tagged(quality: float, body: str = "") -> str:
    return f"<q={quality:.3f}>{body}"


class StubGrader:
    """Reads the quality a scripted artifact declares. Untagged text scores zero. `cost` stands
    in for what a real grading call would charge the treasury."""

    def __init__(self, cost: Micros = 0):
        self.cost = cost

    def grade(self, spec: str, rubric: str, artifact: str) -> Grade:
        m = _TAG.search(artifact or "")
        return Grade(min(1.0, max(0.0, float(m.group(1)))) if m else 0.0, self.cost)
