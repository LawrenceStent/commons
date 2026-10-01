"""Domain events: what happened, as data. The services publish them; subscribers decide what follows (what co-ops are
told, what telemetry records). An event refers to the aggregate it's about as it is at the moment it's published.

One family per section; each event names what happened, never what anyone should do about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.contract import Contract
from commons.domain.gate import Request
from commons.domain.grading import Grade
from commons.domain.knowledge import Playbook
from commons.domain.market import MarketJob
from commons.domain.population import Proposal
from commons.domain.ratings import Rating
from commons.domain.ventures import Venture


class Event:
    """Base of every domain event."""


# ── contracts ──────────────────────────────────────────────────
@dataclass(frozen=True)
class ContractOpened(Event):
    contract: Contract


@dataclass(frozen=True)
class ContractAwarded(Event):
    contract: Contract
    losers: tuple[str, ...]


@dataclass(frozen=True)
class ContractDelivered(Event):
    contract: Contract
    judged_by_grader: bool


@dataclass(frozen=True)
class ContractExpired(Event):
    contract: Contract


@dataclass(frozen=True)
class ContractFailed(Event):
    """The contractor didn't deliver in time."""
    contract: Contract


@dataclass(frozen=True)
class ContractWithdrawn(Event):
    """The job it was for failed."""
    contract: Contract


@dataclass(frozen=True)
class ContractReviewed(Event):
    contract: Contract
    accepted: bool
    reason: str


@dataclass(frozen=True)
class ContractDefaulted(Event):
    """The prime couldn't pay what it owed."""
    contract: Contract


@dataclass(frozen=True)
class AuditFiled(Event):
    contract: Contract


@dataclass(frozen=True)
class AuditUpheld(Event):
    contract: Contract
    score: float


@dataclass(frozen=True)
class AuditOverturned(Event):
    contract: Contract
    score: float
    owed: int
    fee: int


@dataclass(frozen=True)
class AuditUnpaid(Event):
    """The audit found for the contractor, but the prime can't pay."""
    contract: Contract


@dataclass(frozen=True)
class AuditCancelled(Event):
    """The grader stayed down; the contractor's fee is refunded and the dispute may be filed again."""
    contract: Contract
    extra: dict = field(default_factory=dict)


# ── jobs ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class JobPosted(Event):
    job: MarketJob


@dataclass(frozen=True)
class JobExpired(Event):
    job: MarketJob


@dataclass(frozen=True)
class BondUnaffordable(Event):
    claimant: str
    job: MarketJob
    bond: int


@dataclass(frozen=True)
class JobClaimed(Event):
    job: MarketJob
    claimants: tuple[str, ...]  # everyone who asked, in the order they asked
    bond: int


@dataclass(frozen=True)
class JobSubmitted(Event):
    job: MarketJob


@dataclass(frozen=True)
class GradingDelayed(Event):
    job: MarketJob
    error: str


@dataclass(frozen=True)
class JobDeferred(Event):
    """Passed for now; its outcome settles later."""
    job: MarketJob


@dataclass(frozen=True)
class JobAwaitingPayment(Event):
    """Passed; paid at the end of the cycle (`note` says how, in the economy's words)."""
    job: MarketJob
    note: str


@dataclass(frozen=True)
class JobPaid(Event):
    job: MarketJob
    payout: int
    mean: float
    share: int
    payer: str
    royalties: dict
    taxed: bool


@dataclass(frozen=True)
class JobFailed(Event):
    job: MarketJob
    why: str


@dataclass(frozen=True)
class PoolShared(Event):
    """The economy's pool was shared among the cycle's passing work."""
    pool: int
    asked: int
    jobs: int


# ── grading and model calls ────────────────────────────────────
@dataclass(frozen=True)
class ModelCalled(Event):
    community: str
    role: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_hit: float | None
    cost: int
    ms: int | None
    real: bool


@dataclass(frozen=True)
class PartGraded(Event):
    job: str
    part: str
    grade: Grade
    audit: str | None = None


# ── ventures ───────────────────────────────────────────────────
@dataclass(frozen=True)
class VentureDelayed(Event):
    venture: Venture
    error: str


@dataclass(frozen=True)
class VentureWaiting(Event):
    """Scored, but this cycle's budget went to better-scored ventures."""
    venture: Venture


@dataclass(frozen=True)
class VentureRejected(Event):
    venture: Venture


@dataclass(frozen=True)
class VentureApproved(Event):
    venture: Venture
    job: MarketJob


# ── population ─────────────────────────────────────────────────
@dataclass(frozen=True)
class SpawnProposed(Event):
    proposal: Proposal
    asked: tuple[str, ...]  # the co-ops that may second it


@dataclass(frozen=True)
class SpawnFailed(Event):
    proposal: Proposal


@dataclass(frozen=True)
class Spawned(Event):
    proposal: Proposal
    agent: str
    seconded_by: str
    members: int
    fee: int


@dataclass(frozen=True)
class Retired(Event):
    community: str
    agent: str
    members: int


@dataclass(frozen=True)
class Forked(Event):
    parent: str
    child: str
    members: int
    capabilities: tuple[str, ...]
    share: int


@dataclass(frozen=True)
class MergeOffered(Event):
    proposal: Proposal


@dataclass(frozen=True)
class Merged(Event):
    proposal: Proposal
    joiner: str
    target: str
    moved: int
    members: int


@dataclass(frozen=True)
class Learned(Event):
    community: str
    capability: str
    cost: int
    playbook: str | None
    royalty: int
    author: str | None


@dataclass(frozen=True)
class ProposalExpired(Event):
    proposal: Proposal


# ── the gate and the web ───────────────────────────────────────
@dataclass(frozen=True)
class GateRequested(Event):
    request: Request


@dataclass(frozen=True)
class GateRequestExpired(Event):
    request: Request


@dataclass(frozen=True)
class GateDecided(Event):
    request: Request


@dataclass(frozen=True)
class WebRead(Event):
    """An approved or allowed request ran."""
    request: Request
    ok: bool


@dataclass(frozen=True)
class QueuedReadRan(Event):
    """A request that waited for approval ran; the co-op that asked is told the result."""
    request: Request
    message: str


# ── ratings, knowledge, records ────────────────────────────────
@dataclass(frozen=True)
class WorkRated(Event):
    rating: Rating
    job: str
    rated: tuple[tuple[str, str], ...]  # (co-op, capability) for each part rated


@dataclass(frozen=True)
class PlaybookPublished(Event):
    playbook: Playbook


@dataclass(frozen=True)
class GossipHeard(Event):
    heard: int


@dataclass(frozen=True)
class ScorecardBreached(Event):
    metric: str
    value: float
    floor: float


@dataclass(frozen=True)
class CycleRecorded(Event):
    """The end of a cycle: the numbers the dashboard draws."""
    summary: dict


@dataclass(frozen=True)
class OperatorReloaded(Event):
    """The operator's folder changed and was read again."""
    coops: tuple[str, ...]
    errors: tuple[str, ...]
