"""Ventures: what a proposal is, its appraisal, and the fixed formula that prices it. See application/ventures.py."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from commons.domain.compute import Usage
from commons.domain.ids import IdeaId, JobId
from commons.domain.money import Micros
from commons.domain.status import VentureStatus

MAX_PARTS = 3
MAX_TEXT = 600


@dataclass
class Venture:
    id: str
    proposer: str
    title: str
    pitch: str
    parts: list[tuple[str, str, str]]  # (capability, spec, rubric)
    cycle: int
    status: VentureStatus = VentureStatus.PENDING
    score: int | None = None
    reward: Micros = 0
    reason: str = ""
    job_id: JobId | None = None
    idea_id: IdeaId | None = None


@dataclass(frozen=True)
class Appraisal:
    score: int  # 0..10
    reason: str
    cost: Micros = 0
    model: str | None = None
    price_as: str | None = None
    usage: Usage | None = None
    real: bool = False
    ms: int | None = None


class Appraiser(Protocol):
    def appraise(self, v: Venture) -> Appraisal: ...


class AppraisalError(Exception):
    """The appraiser couldn't answer; the proposal waits for the next cycle."""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def value(score: int, base: int, min_score: int) -> int:
    """The market's price for an appraised venture: nothing below min_score, then 0.5x to 1.5x the base."""
    if score < min_score:
        return 0
    return round(base * (0.5 + score / 10))


# ── appraisers ─────────────────────────────────────────────────
class StubAppraiser:
    """For scripted runs and tests: a fixed score, so behaviour is deterministic."""

    def __init__(self, score: int = 6):
        self.score = score

    def appraise(self, v: Venture) -> Appraisal:
        return Appraisal(self.score, "stub appraisal")

