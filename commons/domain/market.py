"""Jobs: the shape every society's work takes, whatever the pack.

A job has parts, one per capability, each with a spec and a rubric. Where jobs come from is a pack's
`WorkSource` (commons/domain/pack.py); how parts are judged is in commons/domain/grading.py.

    open     on the board             -> claimed (allocated to a prime), expired (nobody claimed it in time)
    claimed  parts in progress        -> graded (passed; waiting for a deferred outcome or this cycle's grants),
                                         paid, failed
    graded   waiting                  -> graded (a deferred outcome that passes then waits for grants), paid, failed

The lifecycle is the table below; every move is a method; any other move raises DomainError.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.errors import DomainError
from commons.domain.format import Format
from commons.domain.money import Micros
from commons.domain.status import JobStatus

S = JobStatus
TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    S.OPEN: {S.CLAIMED, S.EXPIRED},
    S.CLAIMED: {S.GRADED, S.PAID, S.FAILED},
    S.GRADED: {S.GRADED, S.PAID, S.FAILED},
    S.PAID: set(), S.FAILED: set(), S.EXPIRED: set(),
}


@dataclass
class Part:
    capability: str
    spec: str
    rubric: str
    artifact: str | None = None
    source: str | None = None  # "self" or a contract id
    cites: tuple[str, ...] = ()
    format: Format = field(default_factory=Format)  # checked by rule at hand-in (commons/domain/format.py)


@dataclass
class MarketJob:
    id: str
    title: str
    reward: Micros
    parts: dict[str, Part]
    posted: int
    deadline: int  # claim-by while on the board; submit-by once claimed
    prime: str | None = None
    status: JobStatus = JobStatus.OPEN
    scores: dict[str, float] = field(default_factory=dict)
    bond: Micros = 0  # posted by the prime on allocation; returned when paid, forfeited if the job fails
    settle_at: int | None = None  # for deferred outcomes: the cycle the grader settles it

    @property
    def complete(self) -> bool:
        return all(p.artifact is not None for p in self.parts.values())

    @property
    def mean_score(self) -> float:
        return sum(self.scores.values()) / len(self.scores) if self.scores else 1.0

    def passed(self, pass_score: float) -> bool:
        """Every graded part reached the pass mark."""
        return min(self.scores.values()) >= pass_score

    def value(self, quality_pay: float) -> int:
        """What passing work is worth: the reward, with `quality_pay` of it scaled by the mean part score."""
        return round(self.reward * (1 - quality_pay + quality_pay * self.mean_score))

    def _move(self, to: JobStatus) -> None:
        if to not in TRANSITIONS[self.status]:
            raise DomainError(f"{self.id} can't go from {self.status} to {to}")
        self.status = to

    # ── the moves ──────────────────────────────────────────────
    def claim(self, prime: str, *, deadline: int, bond: Micros = 0) -> None:
        self._move(S.CLAIMED)
        self.prime, self.deadline, self.bond = prime, deadline, bond

    def expire(self) -> None:
        self._move(S.EXPIRED)

    def fill(self, capability: str, artifact: str, *, source: str, cites: tuple[str, ...] = ()) -> None:
        """A part is done: by the prime itself (`source="self"`) or through a contract (its id)."""
        if self.status != S.CLAIMED:
            raise DomainError(f"{self.id} isn't being worked on: it is {self.status}")
        part = self.parts.get(capability)
        if part is None:
            raise DomainError(f"{self.id} has no {capability} part")
        if part.artifact is not None:
            raise DomainError(f"the {capability} part of {self.id} is already done")
        part.artifact, part.source, part.cites = artifact, source, tuple(cites)

    def record_score(self, capability: str, score: float) -> None:
        self.scores[capability] = score

    def defer(self, *, until: int) -> None:
        """Passed for now; its outcome settles at cycle `until`."""
        self._move(S.GRADED)
        self.settle_at = until

    def await_grants(self) -> None:
        """Passed; paid from this cycle's grants at the end of the cycle."""
        self._move(S.GRADED)

    def pay(self) -> None:
        self._move(S.PAID)

    def fail(self) -> None:
        self._move(S.FAILED)

    def release_bond(self) -> int:
        """The bond, once: returned or forfeited by the caller."""
        bond, self.bond = self.bond, 0
        return bond
