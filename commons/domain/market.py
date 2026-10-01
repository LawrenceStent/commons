"""Jobs: the shape every society's work takes, whatever the pack.

A job has parts, one per capability, each with a spec and a rubric. Where jobs come from is a pack's
`WorkSource` (sim/pack.py); how parts are judged is in society/grading.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.status import JobStatus


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
    status: JobStatus = JobStatus.OPEN
    scores: dict[str, float] = field(default_factory=dict)
    bond: int = 0  # posted by the prime on allocation; returned when paid, forfeited if the job fails
    settle_at: int | None = None  # for deferred outcomes: the cycle the grader settles it

    @property
    def complete(self) -> bool:
        return all(p.artifact is not None for p in self.parts.values())
