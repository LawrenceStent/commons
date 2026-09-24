"""The mock market: synthetic demand and a grader that decides what it pays for.

Jobs are small on purpose: every part is a few lines of text a model can write and a
grader can judge in one cheap call. Scripted policies write artifacts that carry their
quality in a tag, `<q=0.83>`, which `StubGrader` reads back; live runs use an LLM grader.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Protocol

CAPABILITIES = ("research", "build", "design", "write")

PRODUCTS = (
    "a reusable coffee cup", "a budgeting app for students", "a bike repair kit",
    "a sleep-tracking ring", "a sourdough starter kit", "a plant-watering sensor",
    "a language-learning podcast", "a standing desk converter", "a trail running vest",
    "a password manager for families", "a home composting bin", "a noise-cancelling kids' headset",
)

PART_TEMPLATES: dict[str, tuple[str, str]] = {
    "research": (
        "List the three considerations a buyer of {product} cares about most, one line each.",
        "Exactly three lines; each is specific to {product}, not generic; no marketing fluff.",
    ),
    "build": (
        "Write a Python function `validate_order(order: dict) -> list[str]` for {product} orders "
        "with keys name, qty, unit_price. Return a list of error strings; empty if valid.",
        "Valid Python; checks presence and types of all three keys; qty must be a positive int; "
        "unit_price a non-negative number; at most 20 lines.",
    ),
    "design": (
        "Propose a product name and a tagline of at most six words for {product}.",
        "Name is original and pronounceable; tagline is at most six words and says what it does.",
    ),
    "write": (
        "Write a product description of 50 to 70 words for {product}.",
        "Between 50 and 70 words; concrete benefits; no invented certifications or statistics.",
    ),
}


@dataclass
class Part:
    capability: str
    spec: str
    rubric: str
    artifact: str | None = None
    source: str | None = None  # "self" or a contract id
    cites: tuple[str, ...] = ()


@dataclass
class MarketJob:
    id: str
    title: str
    reward: int
    parts: dict[str, Part]
    posted: int
    deadline: int  # claim-by while on the board; submit-by once claimed
    prime: str | None = None
    status: str = "open"  # open | claimed | paid | failed | expired
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return all(p.artifact is not None for p in self.parts.values())


def generate_job(rng: random.Random, job_id: str, cycle: int, reward: int, board_ttl: int, parts: int = 2) -> MarketJob:
    product = rng.choice(PRODUCTS)
    caps = sorted(rng.sample(CAPABILITIES, parts))
    return MarketJob(
        id=job_id,
        title=f"Launch kit for {product}",
        reward=reward,
        parts={
            c: Part(c, PART_TEMPLATES[c][0].format(product=product), PART_TEMPLATES[c][1].format(product=product))
            for c in caps
        },
        posted=cycle,
        deadline=cycle + board_ttl,
    )


@dataclass(frozen=True)
class Grade:
    score: float  # 0..1
    cost: int = 0  # micro-dollars spent grading, charged to the treasury
    reason: str = ""


class Grader(Protocol):
    def grade(self, spec: str, rubric: str, artifact: str) -> Grade: ...


_TAG = re.compile(r"<q=([0-9.]+)>")


def tagged(quality: float, body: str = "") -> str:
    return f"<q={quality:.3f}>{body}"


class StubGrader:
    """Reads the quality a scripted artifact declares. Untagged text scores zero."""

    def grade(self, spec: str, rubric: str, artifact: str) -> Grade:
        m = _TAG.search(artifact or "")
        return Grade(min(1.0, max(0.0, float(m.group(1)))) if m else 0.0)
