"""A contract: one part of a job, bought from another co-op through the contract-net.

    open       taking bids                -> awarded (the prime picks a bid), expired (no award in time),
                                             withdrawn (the prime did the part itself, or the job failed)
    awarded    advance paid               -> delivered, failed (no delivery in time)
    delivered  waiting for judgement      -> accepted, rejected, defaulted (the prime couldn't pay)
    rejected   may go to audit            -> accepted (overturned), defaulted (overturned, but the prime can't pay)

The lifecycle is the table below; every move is a method; any other move raises DomainError.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.errors import DomainError
from commons.domain.ids import JobId
from commons.domain.money import Micros
from commons.domain.status import LIVE_CONTRACT, ContractStatus

S = ContractStatus
TRANSITIONS: dict[ContractStatus, set[ContractStatus]] = {
    S.OPEN: {S.AWARDED, S.EXPIRED, S.WITHDRAWN},
    S.AWARDED: {S.DELIVERED, S.FAILED},
    S.DELIVERED: {S.ACCEPTED, S.REJECTED, S.DEFAULTED},
    S.REJECTED: {S.ACCEPTED, S.DEFAULTED},  # an audit can overturn a rejection
    S.ACCEPTED: set(), S.FAILED: set(), S.DEFAULTED: set(), S.EXPIRED: set(), S.WITHDRAWN: set(),
}


@dataclass
class Contract:
    id: str
    job_id: JobId
    capability: str
    prime: str
    spec: str
    rubric: str
    max_price: Micros
    advance_frac: float
    announced: int
    deadline: int
    bids: dict[str, int] = field(default_factory=dict)
    status: ContractStatus = S.OPEN
    winner: str | None = None
    price: Micros | None = None
    advance: Micros = 0
    artifact: str | None = None
    cites: tuple[str, ...] = ()
    reason: str = ""
    winner_attested: bool = False
    closed: int | None = None
    disputed: bool = False

    @property
    def live(self) -> bool:
        return self.status in LIVE_CONTRACT

    @property
    def owed(self) -> int:
        """What the prime still owes the winner after the advance."""
        return (self.price or 0) - self.advance

    def _move(self, to: ContractStatus) -> None:
        if to not in TRANSITIONS[self.status]:
            raise DomainError(f"{self.id} can't go from {self.status} to {to}")
        self.status = to

    def _close(self, to: ContractStatus, at: int | None) -> None:
        self._move(to)
        self.closed = at

    # ── the moves ──────────────────────────────────────────────
    def bid(self, bidder: str, price: Micros) -> None:
        if self.status != S.OPEN:
            raise DomainError(f"{self.id} can't take bids: it is {self.status}")
        self.bids[bidder] = price

    def award(self, bidder: str, price: Micros, advance: Micros, *, deliver_by: int) -> None:
        self._move(S.AWARDED)
        self.winner, self.price, self.advance, self.deadline = bidder, price, advance, deliver_by

    def deliver(self, artifact: str, cites: tuple[str, ...], *, review_by: int) -> None:
        self._move(S.DELIVERED)
        self.artifact, self.cites, self.deadline = artifact, cites, review_by

    def accept(self, reason: str, *, at: int) -> None:
        self.reason = reason
        self._close(S.ACCEPTED, at)

    def reject(self, reason: str, *, at: int) -> None:
        self.reason = reason
        self._close(S.REJECTED, at)

    def overturn(self, reason: str, *, at: int) -> None:
        """An audit found for the contractor: the rejection becomes an acceptance."""
        if self.status != S.REJECTED:
            raise DomainError(f"{self.id} can't be overturned: it is {self.status}")
        self.reason = reason
        self._close(S.ACCEPTED, at)

    def expire(self, *, at: int) -> None:
        self._close(S.EXPIRED, at)

    def fail(self, *, at: int) -> None:
        self._close(S.FAILED, at)

    def default(self, *, at: int) -> None:
        self._close(S.DEFAULTED, at)

    def withdraw(self, *, at: int | None) -> None:
        self._close(S.WITHDRAWN, at)

    # ── disputes and ratings ───────────────────────────────────
    def file_dispute(self) -> None:
        if self.status != S.REJECTED:
            raise DomainError(f"{self.id} can't be disputed: it is {self.status}")
        if self.disputed:
            raise DomainError(f"{self.id} has already been disputed")
        self.disputed = True

    def drop_dispute(self) -> None:
        """The audit couldn't be held (the grader stayed down): it may be filed again."""
        self.disputed = False

    def rated_by_winner(self) -> None:
        self.winner_attested = True
