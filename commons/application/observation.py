"""What a community sees at the start of its turn, and what it can do during it.

Scripted policies read these objects directly; the LLM runtime renders them as text and
exposes `ActionsAPI` as tools. Nothing here imports the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from commons.domain.format import Format
from commons.domain.ids import ContractId, GoalId, IdeaId, JobId, PassageId, PlaybookId, ProposalId
from commons.domain.money import Micros


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
    format: Format = Format()  # what its text must look like, checked by rule at hand-in
    independent: bool = False  # another co-op must do it (nobody who did another part of the job)


@dataclass(frozen=True)
class JobView:
    id: str
    title: str
    reward: Micros
    parts: tuple[PartView, ...]
    deadline: int  # claim-by for board jobs, submit-by for claimed ones

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(p.capability for p in self.parts)


@dataclass(frozen=True)
class BidView:
    bidder: str
    price: Micros
    trust: float  # my first-hand + heard score for this bidder in this capability
    standing: float  # the commons' pooled view
    eligible: bool = True  # False: the commons refuses this bidder (see World.eligible)
    refused_because: str = ""


@dataclass(frozen=True)
class ContractView:
    id: str
    job_id: JobId
    capability: str
    prime: str
    spec: str
    rubric: str
    max_price: Micros
    advance_frac: float
    announced: int
    bids: tuple[BidView, ...] = ()  # only visible to the prime
    my_bid: int | None = None
    winner: str | None = None
    price: Micros | None = None
    artifact: str | None = None  # visible to the prime once delivered, and to the contractor
    deadline: int | None = None
    status: str = "open"  # open | awarded | delivered | accepted | rejected | failed | defaulted | expired | withdrawn
    format: Format = Format()  # what the delivery's text must look like, checked by rule at hand-in


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
class GoalView:
    id: str
    title: str
    status: str
    steps: tuple[tuple[str, bool, str], ...]  # (text, done, note)
    progress: float


@dataclass(frozen=True)
class IdeaView:
    id: str
    title: str
    detail: str
    cycle: int
    status: str


@dataclass(frozen=True)
class VentureView:
    id: str
    title: str
    status: str  # pending | approved | rejected
    score: int | None
    reward: Micros
    reason: str
    job_id: JobId | None
    cycle: int


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
    owed: Micros = 0  # remainders I still owe on contracts I awarded
    spawn_requests: tuple[ProposalView, ...] = ()  # others asking for a second
    merge_offers: tuple[ProposalView, ...] = ()  # communities offering to join me
    my_proposals: tuple[ProposalView, ...] = ()
    to_dispute: tuple[ContractView, ...] = ()  # my rejected deliveries I can still take to audit
    claim_limit: int = 2  # the most open jobs I may hold (see Actions.claim)
    refused_contracts: int = 0  # open contracts hidden because the commons would refuse my bid
    ventures: tuple[VentureView, ...] = ()  # my recent venture proposals
    efficiency: dict = field(default_factory=dict)  # earned vs spent on thinking, since the start
    pending_claims: tuple[str, ...] = ()  # jobs I've claimed this cycle, allocated at its end
    doctrine: str = ""  # how my co-op works, set at founding
    archive: tuple = (0, ())  # (passages, source files) of the society's reference archive
    web: str = ""  # what the operator's gate allows (empty: no web)
    grants: tuple | None = None  # grant economy: (pool now, budget per cycle); None in a market economy
    desk: str = ""  # what I see of the pack's desk (commons/domain/desk.py); empty without one
    desk_tools: tuple = ()  # the desk's tool schemas, offered beside the kernel's
    goals: tuple[GoalView, ...] = ()  # my active goals
    ideas: tuple[IdeaView, ...] = ()  # my most recent ideas
    params: dict[str, int | float] = field(default_factory=dict)


class MarketActions(Protocol):
    """Jobs and the contract-net."""

    def claim(self, job_id: JobId) -> Outcome: ...
    def announce(self, job_id: JobId, capability: str, max_price: Micros, advance_frac: float) -> Outcome: ...
    def do_part(self, job_id: JobId, capability: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome: ...
    def bid(self, contract_id: ContractId, price: Micros) -> Outcome: ...
    def award(self, contract_id: ContractId, bidder: str) -> Outcome: ...
    def deliver(self, contract_id: ContractId, artifact: str, cites: tuple[str, ...] = ()) -> Outcome: ...
    def review(self, contract_id: ContractId, accept: bool, reason: str = "") -> Outcome: ...
    def attest(self, contract_id: ContractId, outcome: float) -> Outcome: ...
    def dispute(self, contract_id: ContractId, reason: str) -> Outcome: ...


class PopulationActions(Protocol):
    """Changing the co-op itself."""

    def propose_spawn(self, role: str) -> Outcome: ...
    def second_spawn(self, proposal_id: ProposalId) -> Outcome: ...
    def retire(self) -> Outcome: ...
    def fork(self, name: str, members: int, capabilities: tuple[str, ...], charter: str = "") -> Outcome: ...
    def propose_merge(self, target: str) -> Outcome: ...
    def accept_merge(self, proposal_id: ProposalId) -> Outcome: ...
    def learn(self, capability: str, playbook_id: PlaybookId | None = None) -> Outcome: ...


class KnowledgeActions(Protocol):
    """The library, the archive and the web."""

    def publish(self, capability: str, title: str, text: str) -> Outcome: ...
    def read_playbook(self, playbook_id: PlaybookId) -> Outcome: ...
    def search_archive(self, query: str) -> Outcome: ...
    def read_archive(self, passage_ids: PassageId | list[PassageId]) -> Outcome: ...
    def web_search(self, query: str) -> Outcome: ...
    def web_fetch(self, url: str) -> Outcome: ...


class PlanningActions(Protocol):
    """Ventures, ideas, goals, notes, and spending on its own work."""

    def propose_venture(self, title: str, pitch: str, parts: list, idea_id: IdeaId | None = None) -> Outcome: ...
    def idea(self, title: str, detail: str = "") -> Outcome: ...
    def set_goal(self, title: str, steps: list[str], idea_id: IdeaId | None = None) -> Outcome: ...
    def update_goal(self, goal_id: GoalId, step: int | None = None, done: bool | None = None, note: str = "",
                    status: str | None = None) -> Outcome: ...
    def note(self, text: str) -> Outcome: ...
    def spend(self, amount: Micros, memo: str) -> Outcome: ...


class DeskActions(Protocol):
    """The pack's own tools, if it has a desk."""

    def desk_call(self, tool: str, args: dict) -> Outcome: ...


class ActionsAPI(MarketActions, PopulationActions, KnowledgeActions, PlanningActions, DeskActions, Protocol):
    """Everything a community can do (the union of the roles above). Each call returns an Outcome the caller can read.
    An agent that needs only some of it can depend on just those roles."""
