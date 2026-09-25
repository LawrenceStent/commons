"""What a community sees at the start of its turn, and what it can do during it.

Scripted policies read these objects directly; the LLM runtime renders them as text and
exposes `ActionsAPI` as tools. Nothing here imports the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str
    id: str | None = None

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Event:
    """Something that happened to this community since its last turn."""

    cycle: int
    kind: str  # e.g. awarded, bid_lost, paid, rejected, accepted, expired, royalty, job_paid, job_failed
    text: str
    ref: str | None = None


@dataclass(frozen=True)
class PartView:
    capability: str
    spec: str
    rubric: str
    done: bool
    source: str | None  # "self" or a contract id
    pending: str | None = None  # status of the contract in flight for this part: open | awarded | delivered


@dataclass(frozen=True)
class JobView:
    id: str
    title: str
    reward: int
    parts: tuple[PartView, ...]
    deadline: int  # claim-by for board jobs, submit-by for claimed ones

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(p.capability for p in self.parts)


@dataclass(frozen=True)
class BidView:
    bidder: str
    price: int
    trust: float  # my first-hand + heard score for this bidder in this capability
    standing: float  # the commons' pooled view


@dataclass(frozen=True)
class ContractView:
    id: str
    job_id: str
    capability: str
    prime: str
    spec: str
    rubric: str
    max_price: int
    advance_frac: float
    announced: int
    bids: tuple[BidView, ...] = ()  # only visible to the prime
    my_bid: int | None = None
    winner: str | None = None
    price: int | None = None
    artifact: str | None = None  # visible to the prime once delivered, and to the contractor
    deadline: int | None = None
    status: str = "open"  # open | awarded | delivered | accepted | rejected | failed | defaulted | expired | withdrawn


@dataclass(frozen=True)
class PeerView:
    name: str
    capabilities: tuple[str, ...]
    members: int
    standing: float
    trust: dict[str, float]  # capability -> my score


@dataclass(frozen=True)
class PlaybookView:
    id: str
    capability: str
    author: str
    title: str
    uses: int


@dataclass(frozen=True)
class ProposalView:
    id: str
    kind: str  # spawn | merge
    proposer: str
    deadline: int
    detail: str  # spawn: the new member's role; merge (my own): the target
    standing: float  # the commons' view of the proposer


@dataclass(frozen=True)
class Observation:
    cycle: int
    name: str
    charter: str
    capabilities: tuple[str, ...]
    members: int
    funded: int  # members the purse could fund this cycle
    capacity: int  # actions left this turn
    purse: int
    standing: float
    board: tuple[JobView, ...]  # unclaimed market jobs
    my_jobs: tuple[JobView, ...]  # jobs I'm prime on
    open_contracts: tuple[ContractView, ...]  # others' announcements I could bid on
    my_announcements: tuple[ContractView, ...]  # contracts I announced, not yet awarded
    to_deliver: tuple[ContractView, ...]  # contracts I won
    to_review: tuple[ContractView, ...]  # deliveries waiting on my review
    to_attest: tuple[ContractView, ...]  # closed contracts where I may rate the prime
    peers: tuple[PeerView, ...]
    library: tuple[PlaybookView, ...]
    events: tuple[Event, ...]
    journal: tuple[str, ...] = ()
    track: dict[str, int] = field(default_factory=dict)  # capability -> work of mine that was paid for
    owed: int = 0  # remainders I still owe on contracts I awarded
    spawn_requests: tuple[ProposalView, ...] = ()  # others asking for a second
    merge_offers: tuple[ProposalView, ...] = ()  # communities offering to join me
    my_proposals: tuple[ProposalView, ...] = ()
    to_dispute: tuple[ContractView, ...] = ()  # my rejected deliveries I can still take to audit
    params: dict[str, int | float] = field(default_factory=dict)


class ActionsAPI(Protocol):
    """Everything a community can do. Each call returns an Outcome the caller can read."""

    def claim(self, job_id: str) -> Outcome: ...
    def announce(self, job_id: str, capability: str, max_price: int, advance_frac: float) -> Outcome: ...
    def do_part(self, job_id: str, capability: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome: ...
    def bid(self, contract_id: str, price: int) -> Outcome: ...
    def award(self, contract_id: str, bidder: str) -> Outcome: ...
    def deliver(self, contract_id: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome: ...
    def review(self, contract_id: str, accept: bool, reason: str = "") -> Outcome: ...
    def attest(self, contract_id: str, outcome: float) -> Outcome: ...
    def publish(self, capability: str, title: str, text: str) -> Outcome: ...
    def read_playbook(self, playbook_id: str) -> Outcome: ...
    def dispute(self, contract_id: str, reason: str) -> Outcome: ...
    def propose_spawn(self, role: str) -> Outcome: ...
    def second_spawn(self, proposal_id: str) -> Outcome: ...
    def retire(self) -> Outcome: ...
    def fork(self, name: str, members: int, capabilities: tuple[str, ...], charter: str = "") -> Outcome: ...
    def propose_merge(self, target: str) -> Outcome: ...
    def accept_merge(self, proposal_id: str) -> Outcome: ...
    def learn(self, capability: str, playbook_id: str | None = None) -> Outcome: ...
    def note(self, text: str) -> Outcome: ...
    def spend(self, amount: int, memo: str) -> Outcome: ...
