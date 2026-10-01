"""The turn-based world: communities act through the actions executor, one turn per cycle.

One cycle:
    floor     treasury pays every community the flat basic budget
    upkeep    each community pays for as many members to think as it can; none funded => silent
    deadlines anything past its deadline expires, fails or defaults (see below)
    market    new jobs go up on the board
    turns     each active community, in random order, sees an Observation and acts
    gossip    communities relay first-hand beliefs; everyone listens
    decay     old evidence fades

The contract-net spans cycles, and every stage has a deadline, so no one can stall another:
    open       bids arrive; the prime awards from the next cycle   -> expired after `bid_window`
    awarded    advance paid; contractor delivers                    -> failed after `deliver_ttl`:
               the prime keeps its complaint, the advance is gone
    delivered  prime reviews and pays the remainder, or rejects     -> after `review_ttl` the
               delivery is accepted by default; if the prime can't pay it has defaulted
A claimed job must be complete by its deadline or it fails. A complete job is graded part by
part; if every part passes, the market pays and revenue splits 70/20/10.

Two economies (`Params.economy`):
    market  every passing job is paid its reward, scaled by quality, by an outside payer (the mock market)
    grant   a funder puts `grant_budget` into a pool each cycle (up to `grant_cap_cycles` budgets banked); at the
            end of the cycle, passing work shares the pool by value (reward scaled by quality), never more than
            its value. What earns is what the grader values, and the budget is fixed however much work is done.

Money in this world is created money (SIM credits); see commons/substrate/ledger.py.
"""

from __future__ import annotations

import random
import threading
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from commons.application.actions import Actions
from commons.application.gate import Gate
from commons.application.graders import GradingError
from commons.application.observation import (
    BidView,
    ContractView,
    Event,
    GoalView,
    IdeaView,
    JobView,
    Observation,
    Outcome,
    PartView,
    PeerView,
    PlaybookView,
    ProposalView,
    VentureView,
)
from commons.application.operator import Operator
from commons.application.population import Proposal, expire_proposals
from commons.application.ports import WebError, WebPort, host_of
from commons.application.ratings import Ratings
from commons.domain.archive import ArchiveIndex
from commons.domain.archive import citations as archive_citations
from commons.domain.community import Community
from commons.domain.gate import Request as GateRequest
from commons.domain.goals import Plans
from commons.domain.grading import Grade, Grader, StubGrader
from commons.domain.market import MarketJob, Part
from commons.domain.pack import Pack
from commons.domain.pack import load as load_pack
from commons.domain.ratings import EVIDENCE
from commons.domain.scorecard import GENERAL
from commons.domain.scorecard import evaluate as evaluate_scorecard
from commons.domain.scorecard import report as scorecard_report
from commons.domain.status import (
    LIVE_CONTRACT,
    ContractStatus,
    JobStatus,
    ProposalStatus,
    RequestStatus,
    VentureStatus,
)
from commons.domain.ventures import AppraisalError, Appraiser, StubAppraiser, Venture
from commons.domain.ventures import value as venture_value
from commons.protocol import Envelope, Message
from commons.protocol.reputation import Gossip
from commons.substrate.activity import ActivityLog
from commons.substrate.bus import Bus, MemoryBus, RateLimited
from commons.substrate.ledger import InsufficientFunds, Ledger, purse
from commons.substrate.meter import Meter
from commons.substrate.registry import Registry
from commons.substrate.reputation import Reputation
from commons.substrate.telemetry import Hub


@dataclass
class Params:
    seed: int = 0
    reputation: bool = True  # False = the control run: primes can't tell bidders apart
    treasury_seed: int = 2_000_000
    treasury_reserve: int = 2_000_000  # the treasury stops taking its 20% at this balance
    purse_seed: int = 150_000
    basic_budget: int = 3_000  # per cycle, to communities whose purse is below floor_cap
    floor_cap: int = 8_000  # two cycles of one member's upkeep
    upkeep: int = 4_000  # per member, per cycle
    actions_per_member: int = 2
    jobs_per_cycle: int = 2
    job_reward: int = 80_000
    parts_per_job: int = 2
    work_cost: int = 10_000  # what a scripted community spends producing one part
    grade_cost: int = 2_000  # notional treasury cost per graded part (StubGrader)
    # Reviews (your decision, 26 Sep, option B): the grader judges every delivery against the part's rubric.
    # Pass = the prime pays the rest; fail = rejected. The grade is reused when the job is graded. The prime
    # had a conflict of interest (rejecting saves money) and LLM primes rejected good work. False restores
    # prime reviews and disputes.
    grader_reviews: bool = True
    # K2, tempo and efficiency: no rule may reward being first.
    # Claims are registered during a cycle and allocated at its end: most trusted, then best fit, then least
    # loaded; ties by a draw seeded from the job. The winner posts a bond (a share of the reward), returned when
    # the job is paid and forfeited to the treasury if it fails, so claiming what you can't finish costs money.
    claim_allocation: bool = True
    claim_bond: float = 0.1
    # Pay scales with quality: this share of the reward depends on the mean part score (1.0 pays in full, 0.5
    # pays 1 - share/2). Every part must still pass. 0 = the old flat reward.
    quality_pay: float = 0.5
    venture_fee: int = 5_000  # paid to the treasury when proposing a venture (deters spam)
    venture_budget: int = 2  # ventures the market will take on per cycle, best-scored first
    venture_min_score: int = 5  # appraisals below this are worth nothing
    grade_retries: int = 3  # cycles a complete job waits for an unavailable grader before it fails
    # K4: the economy. "market" pays each passing job its reward; "grant" shares a fixed budget per cycle among
    # passing work by value (see the module docstring). A pack sets these.
    economy: str = "market"
    grant_budget: int = 0
    grant_cap_cycles: int = 3  # budgets the pool may bank when too little work passes
    outputs_keep: int = 200  # paid work kept in memory for the scorecard (the full record is in the activity log)
    # The world refuses bids (and awards) from anyone below this line, in the commons' pooled standing or in
    # the prime's own record of them for that capability. A rule, not a judgement: in the 1.5 runs LLM primes
    # kept hiring a known defector whose standing had fallen to 0.17.
    bid_floor: float = 0.35
    pass_score: float = 0.5  # every part must grade at least this for the market to pay
    sub_share: float = 0.4  # of job reward a scripted prime offers for each part it lacks
    advance_frac: float = 0.5
    board_ttl: int = 3  # cycles a job stays on the board
    job_ttl: int = 8  # cycles from claim to submission
    bid_window: int = 3  # cycles an announcement stays open
    deliver_ttl: int = 3
    review_ttl: int = 2
    publish_cost: int = 15_000
    gossip_every: int = 5
    gossip_fanout: int = 3
    base_allowance: int = 12
    decay: float = 0.995
    daily_ceiling: int = 10**12
    verify: bool = True
    ledger_path: str = ":memory:"  # a file under runs/ keeps long runs out of RAM
    journal_keep: int = 20
    events_keep: int = 50
    # Let communities think at the same time: model calls run in parallel, but every action takes the
    # world's lock, so state changes one action at a time. Off by default: scripted runs stay
    # deterministic. The catch until K2: when two communities want the same job, whoever's model
    # answers first gets it, which is a small reward for speed.
    parallel_turns: bool = False
    parallel_workers: int = 4
    # model calls for grading and appraisal at once (outside the lock). Verdicts are applied in a fixed order,
    # so results don't depend on which call finishes first. 1 for scripted runs; `commons run` uses 4.
    grading_workers: int = 1
    activity_keep: int = 2000  # entries of the activity log kept in memory
    activity_path: str | None = None  # also append every entry to this JSONL file
    retain: int = 20  # cycles a closed job or contract stays visible before it's dropped
    # population and capabilities (commons/application/population.py)
    max_members: int = 7
    max_communities: int = 12
    spawn_fee: int = 300_000
    spawn_window: int = 3
    merge_window: int = 3
    fork_good_keep: float = 0.5  # share of a parent's good record a fork inherits (bad is kept in full)
    learn_cost: int = 500_000
    learn_playbook_discount: float = 0.4
    learn_royalty: float = 0.1  # of learn_cost, to the author of the playbook learned from
    # disputes
    audit_cost: int = 6_000  # paid by the disputing contractor; refunded by the prime if the audit finds for them
    dispute_window: int = 3


def default_population() -> list[Community]:
    """The default pack's scripted co-ops (kept for callers that predate packs)."""
    return load_pack().population()


@dataclass
class Playbook:
    id: str
    author: str
    capability: str
    title: str = ""
    text: str = ""
    uses: int = 0


@dataclass
class Contract:
    id: str
    job_id: str
    capability: str
    prime: str
    spec: str
    rubric: str
    max_price: int
    advance_frac: float
    announced: int
    deadline: int
    bids: dict[str, int] = field(default_factory=dict)
    status: ContractStatus = ContractStatus.OPEN
    winner: str | None = None
    price: int | None = None
    advance: int = 0
    artifact: str | None = None
    cites: tuple[str, ...] = ()
    reason: str = ""
    winner_attested: bool = False
    closed: int | None = None
    disputed: bool = False


@dataclass
class Snapshot:
    cycle: int
    purse: int
    standing: float
    allowance: int
    active: bool
    thinking: int
    won: int
    delivered_ok: int
    earned: int


class World:
    def __init__(self, params: Params | None = None, population: list[Community] | None = None,
                 hub: Hub | None = None, grader: Grader | None = None, appraiser: Appraiser | None = None,
                 operator: Operator | None = None, pack: Pack | None = None, archive: ArchiveIndex | None = None,
                 ratings: Ratings | None = None, web: WebPort | None = None, gate: Gate | None = None,
                 ledger: Ledger | None = None, bus: Bus | None = None, activity: ActivityLog | None = None):
        """Everything outside the society's rules can be passed in (the model-backed grader and appraiser, the web,
        the ledger, the bus, the activity log); what isn't is built from `params` (see `_default_*` below)."""
        self.params = p = params or Params()
        self.pack = pack or load_pack()  # what this society is for: its work, vocabulary and seed co-ops
        self.hub = hub or Hub()
        self.lock = threading.RLock()  # held for every state change; see parallel_turns
        self.rng = random.Random(p.seed)
        self.cycle = 0
        self.communities = {c.name: c for c in (population or self.pack.population())}
        self.ledger = ledger or _default_ledger(p, self.hub)
        self.meter = Meter(self.ledger, daily_ceiling=p.daily_ceiling, hub=self.hub)
        self.rep = Reputation(decay=p.decay, hub=self.hub)
        self.bus = bus or _default_bus(p, self.hub)
        self.bus.standing = self._standing  # the bus rations messages by this society's trust
        self.registry = self.bus.registry
        self.grader = grader or StubGrader(cost=p.grade_cost)
        self.appraiser = appraiser or StubAppraiser()
        self.operator = operator or Operator(None)
        self.archive = archive or ArchiveIndex()  # the society's reference material, searched on demand
        self.ratings = ratings  # your ratings of a sample of the paid work (commons/application/ratings.py)
        # the web (a WebPort; None = no web at all), behind the gate (commons/application/gate.py), whose policy is
        # the operator's [gate] section
        self.web = web
        self.gate = gate or Gate()
        self.gate.policy = self.operator.gate
        if self.web:
            self.web.set_hosts(self.gate.policy.allow_hosts)
        self.web_pages: dict[str, list[str]] = {}  # url -> archive passage ids, for pages read this run
        self.outputs: deque[dict] = deque(maxlen=p.outputs_keep)  # paid work, newest last: who did what, how it scored
        self.citations: Counter[str] = Counter()  # archive citations checked: valid / invalid
        self._cite_lock = threading.Lock()  # grading runs in threads
        self.grant_queue: list[str] = []  # passing jobs waiting for this cycle's grants
        self.scorecard: list[dict] = []  # the pack's mission metrics plus the general ones, as of the last cycle
        self.ventures: dict[str, Venture] = {}
        self._venture_seq = 0
        self.jobs: dict[str, MarketJob] = {}
        self.contracts: dict[str, Contract] = {}
        self.library: dict[str, Playbook] = {}
        self.journal: dict[str, deque[str]] = {n: deque(maxlen=p.journal_keep) for n in self.communities}
        self.inbox: dict[str, deque[Event]] = {n: deque(maxlen=p.events_keep) for n in self.communities}
        self.history: dict[str, list[Snapshot]] = {n: [] for n in self.communities}
        self.jobs_done = self.jobs_failed = self.jobs_expired = 0
        self.royalties_paid: dict[str, int] = {}
        self.proposals: dict[str, Proposal] = {}
        # grading happens after the turns, outside the lock (see settle_grading)
        self.awaiting_grade: dict[str, int] = {}  # submitted job id -> failed grading attempts so far
        self.pending_audits: dict[str, dict] = {}  # contract id -> {reason, attempts}
        self.pending_reviews: dict[str, int] = {}  # delivered contract id -> failed grading attempts
        self.claims: dict[str, dict[str, int]] = {}  # job id -> {claimant: cycle claimed}, allocated at cycle end
        self.thinking_spend: Counter[str] = Counter()  # µcr of model calls, per co-op
        self.deferred: set[str] = set()  # graded jobs waiting for their outcome (see Grade.settle_after)
        self.transcripts: defaultdict[str, deque] = defaultdict(lambda: deque(maxlen=2))  # LLM turns, newest last
        self.plans: defaultdict[str, Plans] = defaultdict(Plans)  # ideas and goals per community
        self._plan_seq = 0
        self.activity = activity or _default_activity(p)
        self.activity.watch(self.hub)
        self.known_capabilities = set(self.pack.capabilities).union(*(c.capabilities for c in self.communities.values()))
        self._job_seq = self._proposal_seq = 0
        self._stats: dict[str, Counter] = {n: Counter() for n in self.communities}

        self.ledger.transfer("genesis", "treasury", p.treasury_seed, cycle=0, kind="genesis")
        for c in self.communities.values():
            c.strategy.rng = random.Random(f"{p.seed}:{c.name}")
            self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
            self.ledger.transfer("genesis", purse(c.name), p.purse_seed, cycle=0, kind="genesis")

    def _add_community(self, c: Community) -> None:
        """A community born mid-run (a fork). Its history starts empty, not back-filled."""
        p = self.params
        self.communities[c.name] = c
        self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
        self.journal[c.name] = deque(maxlen=p.journal_keep)
        self.inbox[c.name] = deque(maxlen=p.events_keep)
        self.history[c.name] = []
        self._stats[c.name] = Counter()

    # ── helpers ────────────────────────────────────────────────
    def _standing(self, name: str) -> float:
        return self.rep.standing(name) if self.params.reputation else 0.5

    def eligible(self, prime: str, bidder: str, capability: str) -> tuple[bool, str]:
        """Whether the commons lets `bidder` work for `prime` in `capability`. Deterministic; with
        reputation switched off (the control run) everyone is neutral and eligible."""
        floor = self.params.bid_floor
        standing = self._standing(bidder)
        if standing < floor:
            return False, f"{bidder}'s standing in the commons is {standing:.2f}, below the {floor:.2f} line"
        trust = self._trust(prime, bidder, capability)
        if trust < floor:
            return False, f"{prime}'s record of {bidder} in {capability} is {trust:.2f}, below the {floor:.2f} line"
        return True, ""

    def _trust(self, observer: str, subject: str, capability: str) -> float:
        return self.rep.score(observer, subject, capability) if self.params.reputation else 0.5

    def _tell(self, name: str, kind: str, text: str, ref: str | None = None) -> None:
        self.inbox[name].append(Event(self.cycle, kind, text, ref))

    def _stat(self, name: str, key: str, n: int = 1) -> None:
        self._stats[name][key] += n

    def _stage(self, c: Contract, stage: str, **kw) -> None:
        self.hub.emit("contract.stage", self.cycle, id=c.id, capability=c.capability, prime=c.prime,
                      winner=c.winner, stage=stage, price=c.price, max_price=c.max_price, bids=dict(c.bids), **kw)

    def _send(self, c: Community, msg: Message) -> bool:
        try:
            self.bus.publish(Envelope.seal(c.identity, msg, self.cycle))
            return True
        except RateLimited:
            return False

    def _active(self) -> list[Community]:
        return [c for c in self.communities.values() if c.active and not c.dissolved]

    def _living(self) -> list[Community]:
        return [c for c in self.communities.values() if not c.dissolved]

    # ── the cycle ──────────────────────────────────────────────
    def step(self) -> None:
        with self.lock:
            self.cycle += 1
            self.rep.cycle = self.cycle
            if self.operator.reload():  # your directives, context and limits, re-read every cycle
                self.hub.emit("operator.update", self.cycle, coops=sorted(self.operator.views), errors=self.operator.errors)
                self.gate.policy = self.operator.gate
                if self.web:
                    self.web.set_hosts(self.gate.policy.allow_hosts)
            self._gate_cycle()
            self.bus.begin_cycle(self.cycle)
            self._stats = {n: Counter() for n in self.communities}
            self._fund_grants()
            self._apply_ratings()
            self._floor()
            self._upkeep()
            self._deadlines()
            expire_proposals(self)
            self._post_jobs()
            order = self._active()
            self.rng.shuffle(order)  # turn order must not decide who wins
        self._appraise_ventures()
        self._run_approved_web()
        if self.params.parallel_turns and len(order) > 1:
            # the lock is released here: each action takes it, model calls don't
            with ThreadPoolExecutor(max_workers=self.params.parallel_workers) as pool:
                for f in [pool.submit(self._turn, c) for c in order]:
                    f.result()  # re-raise anything a turn raised (a kill-switch, say)
        else:
            with self.lock:
                for c in order:
                    self._turn(c)
        with self.lock:
            self._allocate_claims()
        self.settle_grading()
        with self.lock:
            self._award_grants()
            if self.cycle % self.params.gossip_every == 0:
                self._gossip()
            self.rep.tick()
            self.bus.compact()
            self._prune()
            self._record()

    def run(self, cycles: int) -> World:
        for _ in range(cycles):
            self.step()
        return self

    def _floor(self) -> None:
        """The basic budget tops up poor purses only: enough to think, not enough to coast.
        A community that never wakes can't bank handouts, and a rich one doesn't need them."""
        p = self.params
        for c in self._living():
            if self.ledger.balance(purse(c.name)) >= p.floor_cap:
                continue
            if self.ledger.balance("treasury") < p.basic_budget:
                return
            self.ledger.transfer("treasury", purse(c.name), p.basic_budget, cycle=self.cycle, kind="floor")

    def _upkeep(self) -> None:
        """Each community decides how many members to wake, and pays for them. Thinking is the
        cost of doing business, so it is a choice; none awake means silence this cycle."""
        p = self.params
        for c in list(self.communities.values()):
            c.capacity = 0
            if c.dissolved:
                c.thinking, c.active = 0, False
                continue
            want = c.strategy.wake(self.observe(c))
            c.thinking = max(0, min(c.members, int(want), self.ledger.balance(purse(c.name)) // p.upkeep))
            if c.thinking:
                try:
                    self.meter.charge(c.name, c.thinking * p.upkeep, cycle=self.cycle, memo="upkeep")
                except InsufficientFunds:
                    c.thinking = 0
            c.active = c.thinking > 0
            c.capacity = c.thinking * p.actions_per_member

    def _post_jobs(self) -> None:
        p = self.params
        for _ in range(p.jobs_per_cycle):
            self._job_seq += 1
            job = self.pack.work_source.new_job(self.rng, f"J{self._job_seq}", self.cycle, p.job_reward, p.board_ttl,
                                                p.parts_per_job)
            self.jobs[job.id] = job
            self.hub.emit("market.job", self.cycle, id=job.id, stage="posted", caps=sorted(job.parts), reward=job.reward)

    def _turn(self, c: Community) -> None:
        with self.lock:
            obs = self.observe(c)
            self.inbox[c.name].clear()
        c.strategy.turn(obs, Actions(self, c))

    # ── deadlines ──────────────────────────────────────────────
    def _deadlines(self) -> None:
        now = self.cycle
        for job in self.jobs.values():
            if job.status == JobStatus.OPEN and now > job.deadline:
                job.status = JobStatus.EXPIRED
                self.jobs_expired += 1
                self.hub.emit("market.job", now, id=job.id, stage="expired", caps=sorted(job.parts), reward=job.reward)
            elif job.status == JobStatus.CLAIMED and now > job.deadline and job.id not in self.awaiting_grade:
                self._fail_job(job, "missed its deadline")
        for c in list(self.contracts.values()):
            if c.deadline >= now:
                continue
            if c.status == ContractStatus.OPEN:
                self._close(c, ContractStatus.EXPIRED)
                self._tell(c.prime, "expired", f"{c.id} closed with no award", c.id)
            elif c.status == ContractStatus.AWARDED:
                # non-delivery is objective: the substrate files the prime's complaint for it
                self._close(c, ContractStatus.FAILED)
                self.rep.attest(c.prime, c.winner, c.capability, 0.0)
                self._tell(c.prime, "failed", f"{c.winner} never delivered {c.id}", c.id)
                self._tell(c.winner, "failed", f"you missed the delivery deadline on {c.id}", c.id)
            elif c.status == ContractStatus.DELIVERED and c.id not in self.pending_reviews:
                if self.pay_remainder(c):
                    self.close_review(c, True, "accepted by default: the prime didn't review in time")
                else:
                    self._close(c, ContractStatus.DEFAULTED)
                    self.rep.attest(c.winner, c.prime, c.capability, 0.0)
                    c.winner_attested = True
                    self._tell(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)

    def _close(self, c: Contract, status: str) -> None:
        c.status, c.closed = status, self.cycle
        self._stage(c, status)

    def _prune(self) -> None:
        """Drop closed jobs and contracts after a while, so memory stays flat on long runs."""
        cutoff = self.cycle - self.params.retain
        for k in [k for k, j in self.jobs.items() if j.status not in (JobStatus.OPEN, JobStatus.CLAIMED, JobStatus.GRADED) and j.deadline < cutoff]:
            del self.jobs[k]
        for k in [k for k, c in self.contracts.items() if c.closed is not None and c.closed < cutoff]:
            del self.contracts[k]

    # ── called by the actions executor ────────────────────────
    def contracts_for(self, job_id: str, capability: str, statuses: tuple[str, ...]) -> list[Contract]:
        return [c for c in self.contracts.values()
                if c.job_id == job_id and c.capability == capability and c.status in statuses]

    def open_contract(self, cid: str, job: MarketJob, capability: str, prime: str, max_price: int, advance_frac: float) -> None:
        part = job.parts[capability]
        c = Contract(cid, job.id, capability, prime, part.spec, part.rubric, max_price, advance_frac,
                     announced=self.cycle, deadline=self.cycle + self.params.bid_window)
        self.contracts[cid] = c
        self._stage(c, ContractStatus.OPEN)

    def award_contract(self, c: Contract, bidder: str, price: int, advance: int) -> None:
        c.status, c.winner, c.price, c.advance = ContractStatus.AWARDED, bidder, price, advance
        c.deadline = self.cycle + self.params.deliver_ttl
        self._stat(bidder, "won")
        self._stat(bidder, "earned", advance)
        self._tell(bidder, "awarded", f"you won {c.id} at {price}; advance {advance} paid; deliver by cycle {c.deadline}", c.id)
        for loser in c.bids:
            if loser != bidder:
                self._tell(loser, "bid_lost", f"{c.id} went to another bidder", c.id)
        self._stage(c, ContractStatus.AWARDED)

    def deliver_contract(self, c: Contract, artifact: str, cites: tuple[str, ...]) -> None:
        c.status, c.artifact, c.cites = ContractStatus.DELIVERED, artifact, cites
        c.deadline = self.cycle + self.params.review_ttl
        if self.params.grader_reviews:
            self.pending_reviews[c.id] = 0
            self._tell(c.prime, "delivered", f"{c.winner} delivered {c.id}; the grader judges it at the end of this cycle", c.id)
        else:
            self._tell(c.prime, "delivered", f"{c.winner} delivered {c.id}; review by cycle {c.deadline}", c.id)
        self._stage(c, ContractStatus.DELIVERED)

    def pay_remainder(self, c: Contract) -> bool:
        owed = c.price - c.advance
        try:
            self.ledger.transfer(purse(c.prime), purse(c.winner), owed, cycle=self.cycle, kind="contract", memo=f"settle {c.id}")
        except InsufficientFunds:
            return False
        self._stat(c.winner, "earned", owed)
        return True

    def close_review(self, c: Contract, accept: bool, reason: str) -> None:
        c.reason = reason
        self._close(c, ContractStatus.ACCEPTED if accept else ContractStatus.REJECTED)
        self.rep.attest(c.prime, c.winner, c.capability, 1.0 if accept else 0.0)
        if accept:
            self._stat(c.winner, "ok")
            track = self.communities[c.winner].deliveries
            track[c.capability] = track.get(c.capability, 0) + 1
            self._tell(c.winner, "accepted", f"{c.prime} accepted {c.id} and paid {c.price - c.advance}", c.id)
            job = self.jobs.get(c.job_id)
            if job and job.status == JobStatus.CLAIMED and job.parts[c.capability].artifact is None:
                part = job.parts[c.capability]
                part.artifact, part.source, part.cites = c.artifact, c.id, c.cites
                self.maybe_submit(job)
        else:
            self._tell(c.winner, "rejected", f"{c.prime} rejected {c.id}: {reason or 'no reason given'}", c.id)

    def audit(self, c: Contract, reason: str) -> Outcome:
        """File a dispute. The grader decides at the end of this cycle, outside the world's lock, so an
        audit never holds up other communities (in the third Qwen run one stalled a cycle for 9 minutes)."""
        c.disputed = True
        self.pending_audits[c.id] = {"reason": reason, "attempts": 0}
        self._stage(c, "audit_filed")
        self._tell(c.prime, "audit_filed", f"{c.winner} disputed your rejection of {c.id}; the grader decides this cycle", c.id)
        return Outcome(True, f"audit of {c.id} filed; the grader decides at the end of this cycle")

    def _apply_audit(self, c: Contract, g, reason: str) -> None:
        """The verdict, under the lock. The commons ("audit") files its own first-hand evidence, so the
        verdict moves standing, not any one community's private view."""
        p = self.params
        if g.score < p.pass_score:
            self.rep.attest("audit", c.winner, c.capability, 0.0)
            self._stage(c, "audit_upheld", score=g.score)
            self._tell(c.prime, "audit", f"the audit upheld your rejection of {c.id} ({g.score:.2f})", c.id)
            self._tell(c.winner, "audit", f"the audit upheld the rejection of {c.id}: your delivery scored {g.score:.2f}; the fee is gone", c.id)
            return
        owed = c.price - c.advance
        try:
            # the treasury keeps the fee (it paid for the audit); the prime reimburses the contractor
            self.ledger.transfer(purse(c.prime), purse(c.winner), owed + p.audit_cost,
                                 cycle=self.cycle, kind="audit", memo=f"overturned {c.id}")
            paid = True
        except InsufficientFunds:
            paid = False
        self.rep.attest("audit", c.prime, c.capability, 0.0)
        self.rep.attest("audit", c.winner, c.capability, 1.0)
        if not paid:
            self._close(c, ContractStatus.DEFAULTED)
            self._tell(c.winner, "audit", f"the audit found for you on {c.id}, but {c.prime} can't pay", c.id)
            return
        self._stat(c.winner, "earned", owed + p.audit_cost)
        self._stat(c.winner, "ok")
        c.reason = f"overturned on audit ({g.score:.2f}): {reason}"
        self._close(c, ContractStatus.ACCEPTED)
        self._stage(c, "audit_overturned", score=g.score)
        self._tell(c.prime, "audit", f"the audit overturned your rejection of {c.id}; you paid {owed} plus the {p.audit_cost} fee", c.id)
        job = self.jobs.get(c.job_id)
        if job and job.status == JobStatus.CLAIMED and job.parts[c.capability].artifact is None:
            part = job.parts[c.capability]
            part.artifact, part.source, part.cites = c.artifact, c.id, c.cites
            self.maybe_submit(job)
        self._tell(c.winner, "audit", f"the audit found for you on {c.id} ({g.score:.2f}): {c.prime} paid {owed} plus your {p.audit_cost} fee", c.id)

    def maybe_submit(self, job: MarketJob) -> None:
        """A complete job is submitted for grading at the end of this cycle. Every part must pass for the
        market to pay."""
        if not job.complete or job.status != JobStatus.CLAIMED or job.id in self.awaiting_grade:
            return
        self.awaiting_grade[job.id] = 0
        self._tell(job.prime, "submitted", f"{job.id} is complete and goes to the grader at the end of this cycle", job.id)

    def settle_grading(self) -> None:
        """Grade every submitted job and every filed audit. Model calls run outside the world's lock;
        verdicts and money are applied under it. An unavailable grader is retried next cycle, up to
        `grade_retries` times."""
        with self.lock:
            jobs = []
            for jid in list(self.awaiting_grade):
                job = self.jobs.get(jid)
                if job is None or job.status != JobStatus.CLAIMED:
                    self.awaiting_grade.pop(jid, None)
                    continue
                jobs.append((jid, [(cap, p.spec, p.rubric, p.artifact) for cap, p in sorted(job.parts.items())
                                   if cap not in job.scores]))
            audits = [(cid, c.spec, c.rubric, c.artifact or "") for cid in list(self.pending_audits)
                      if (c := self.contracts.get(cid)) is not None]
            reviews = [(cid, c.spec, c.rubric, c.artifact or "") for cid in list(self.pending_reviews)
                       if (c := self.contracts.get(cid)) is not None and c.status == ContractStatus.DELIVERED]
        tasks = [((jid, cap), spec, rubric, artifact) for jid, parts in jobs for cap, spec, rubric, artifact in parts]
        tasks += [(("audit", cid), spec, rubric, artifact) for cid, spec, rubric, artifact in audits]
        tasks += [(("review", cid), spec, rubric, artifact) for cid, spec, rubric, artifact in reviews]
        verdicts = dict(self._map_calls(lambda t: (t[0], self._try_grade(*t[1:])), tasks))
        with self.lock:
            for jid, parts in jobs:
                self._apply_job_grades(jid, [(cap, verdicts[(jid, cap)]) for cap, *_ in parts])
            for cid, *_ in audits:
                self._settle_audit(cid, verdicts[("audit", cid)])
            for cid, *_ in reviews:
                self._settle_review(cid, verdicts[("review", cid)])
            self._settle_deferred()

    def _map_calls(self, fn, items: list) -> list:
        """Run model calls (outside the lock) up to `grading_workers` at a time; results in input order."""
        workers = self.params.grading_workers
        if workers <= 1 or len(items) <= 1:
            return [fn(i) for i in items]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items))

    def _try_grade(self, spec: str, rubric: str, artifact: str):
        # a rule before any judgement: work citing archive passages that don't exist made them up
        cited = archive_citations(artifact or "")
        missing = [c for c in cited if self.archive.get(c) is None]
        with self._cite_lock:
            self.citations["valid"] += len(cited) - len(missing)
            self.citations["invalid"] += len(missing)
        if missing:
            return Grade(0.0, 0, f"cites archive passages that don't exist ({', '.join(missing[:3])}); a made-up "
                                 f"citation fails the part")
        try:
            return self.grader.grade(spec, rubric, artifact)
        except GradingError as e:
            return e

    def _apply_job_grades(self, jid: str, graded: list) -> None:
        job = self.jobs.get(jid)
        if job is None or job.status != JobStatus.CLAIMED:
            self.awaiting_grade.pop(jid, None)
            return
        errors, defer = [], 0
        for cap, g in graded:
            if isinstance(g, GradingError):
                errors.append(str(g))
                continue
            try:
                # the commons pays for grading; when it can't, the prime whose job it is does
                self._charge_grade(g, job=jid, part=cap, payers=("treasury", purse(job.prime)))
            except InsufficientFunds:
                self.awaiting_grade.pop(jid, None)
                self._fail_job(job, "no one could pay for grading")
                return
            job.scores[cap] = g.score
            defer = max(defer, g.settle_after)
        if errors:
            self.awaiting_grade[jid] += 1
            if self.awaiting_grade[jid] >= self.params.grade_retries:
                self.awaiting_grade.pop(jid)
                self._fail_job(job, "the grader was unavailable")
            else:
                self._tell(job.prime, "grading_delayed", f"{jid} is waiting for the grader: {errors[0]}", jid)
            return
        self.awaiting_grade.pop(jid, None)
        if defer and min(job.scores.values()) >= self.params.pass_score:
            job.status, job.settle_at = JobStatus.GRADED, self.cycle + defer
            self.deferred.add(jid)
            self._tell(job.prime, "job_graded", f"{jid} passed for now; its outcome settles at cycle {job.settle_at}", jid)
            return
        self._finish_job(job)

    def _finish_job(self, job: MarketJob) -> None:
        if min(job.scores.values()) < self.params.pass_score:
            self._fail_job(job, f"a part failed grading ({', '.join(f'{k} {v:.2f}' for k, v in job.scores.items())})")
            return
        if self.params.economy == "grant":
            job.status = JobStatus.GRADED
            self.grant_queue.append(job.id)
            self._tell(job.prime, "job_graded", f"{job.id} passed grading; it shares this cycle's grants at the end "
                                                f"of the cycle", job.id)
            return
        self._pay_job(job)

    def _settle_deferred(self) -> None:
        """Outcomes whose time has come: ask the grader again (if it can), then pay or fail. Under the lock."""
        for jid in sorted(self.deferred):
            job = self.jobs.get(jid)
            if job is None or job.status != JobStatus.GRADED:
                self.deferred.discard(jid)
                continue
            if self.cycle < job.settle_at:
                continue
            self.deferred.discard(jid)
            later = self.grader.settle(job) if hasattr(self.grader, "settle") else None
            if later:
                job.scores.update(later)
            job.status = JobStatus.CLAIMED  # back to the ordinary path for paying or failing
            self._finish_job(job)

    def _settle_review(self, cid: str, g) -> None:
        """The grader's verdict on a delivery decides the contract (option B). Under the lock."""
        c = self.contracts.get(cid)
        if c is None or c.status != ContractStatus.DELIVERED:
            self.pending_reviews.pop(cid, None)
            return
        if isinstance(g, GradingError):
            self.pending_reviews[cid] += 1
            if self.pending_reviews[cid] < self.params.grade_retries:
                return
            self.pending_reviews.pop(cid)
            # the grader stayed down: accept by default, so contractors aren't punished for an outage
            if self.pay_remainder(c):
                self.close_review(c, True, "accepted by default: the grader was unavailable")
            else:
                self._default(c)
            return
        self.pending_reviews.pop(cid)
        self._charge_grade(g, job=c.job_id, part=c.capability, payers=("treasury", purse(c.prime)))
        if g.score < self.params.pass_score:
            self.close_review(c, False, f"failed grading ({g.score:.2f}): {g.reason}"[:300])
            return
        if not self.pay_remainder(c):
            self._default(c)
            return
        job = self.jobs.get(c.job_id)
        if job is not None:
            job.scores[c.capability] = g.score  # reused when the job is graded: no part is graded twice
        self.close_review(c, True, f"passed grading ({g.score:.2f}): {g.reason}"[:300])

    def _default(self, c: Contract) -> None:
        self._close(c, ContractStatus.DEFAULTED)
        self.rep.attest(c.winner, c.prime, c.capability, 0.0)
        c.winner_attested = True
        self._tell(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)

    def _settle_audit(self, cid: str, g) -> None:
        entry = self.pending_audits[cid]
        c = self.contracts.get(cid)
        if c is None:
            self.pending_audits.pop(cid)
            return
        if isinstance(g, GradingError):
            entry["attempts"] += 1
            if entry["attempts"] >= self.params.grade_retries:
                self.pending_audits.pop(cid)
                c.disputed = False  # it may be filed again
                self.ledger.transfer("treasury", purse(c.winner), self.params.audit_cost, cycle=self.cycle, kind="audit",
                                     memo=f"refund {cid}")
                self._tell(c.winner, "audit", f"the grader was unavailable for the audit of {cid}; your fee was refunded", cid)
            return
        self.pending_audits.pop(cid)
        self._charge_grade(g, job=c.job_id, part=c.capability, payers=("treasury", purse(c.winner)), audit=cid)
        self._apply_audit(c, g, entry["reason"])

    # ── the web, behind the gate ───────────────────────────────
    def _gate_cycle(self) -> None:
        """A new cycle for the gate: fresh web budgets, your decisions from file, expired requests. Under the lock."""
        self.gate.begin_cycle()
        for r in self.gate.reload():
            self._gate_decided(r)
        for r in self.gate.expire(self.cycle):
            self._tell(r.coop, "gate", f"{r.id} ({r.tool} {r.target[:80]}) expired without a decision", r.id)
            self.hub.emit("gate.decision", self.cycle, id=r.id, coop=r.coop, status=r.status)

    def gate_decide(self, ids, approve: bool, always: bool = False, reason: str = "") -> list[GateRequest]:
        """Your decisions, from the dashboard. Approved requests run at the start of the next cycle."""
        with self.lock:
            done = self.gate.decide(ids, approve, always, reason)
            for r in done:
                self._gate_decided(r)
            return done

    def _gate_decided(self, r: GateRequest) -> None:
        what = f"{r.tool} {r.target[:80]}"
        if r.status == RequestStatus.DENIED:
            self._tell(r.coop, "gate", f"the operator denied {r.id} ({what})" + (f": {r.reason}" if r.reason else ""), r.id)
        else:
            self._tell(r.coop, "gate", f"the operator approved {r.id} ({what}); it runs at the start of next cycle"
                       + (f", and your reads from {r.host} no longer need approval" if r.always else ""), r.id)
        self.activity.add(self.cycle, r.coop, "operator", "change", "gate", f"{r.status} {r.id}: {what}", r.status == RequestStatus.APPROVED,
                          {"id": r.id, "always": r.always})
        self.hub.emit("gate.decision", self.cycle, id=r.id, coop=r.coop, status=r.status, always=r.always)

    def web_call(self, coop: str, actor: str, tool: str, target: str):
        """A web read an agent asked for. Called WITHOUT the world's lock: the network is slow, so the lock is taken
        only to ask the gate and to record the result."""
        target = str(target).strip()[:500]
        if not self.web or not self.gate.policy.allow_hosts:
            return Outcome(False, "this society has no web access (the operator allows no hosts)")
        if tool == "web_fetch":
            with self.lock:
                if target in self.web_pages:
                    ids = self.web_pages[target]
                    return Outcome(True, f"already read: {target} is archive passages {', '.join(ids)}; use read_archive",
                                   ids[0] if ids else None)
            host = host_of(target)
        else:
            if self.web.search_host is None or self.gate.policy.search == "none":
                return Outcome(False, "this society has no web search; web_fetch a page on an allowed host instead")
            host = self.web.search_host
        with self.lock:
            verdict, r = self.gate.ask(coop, actor, tool, target, host, self.cycle)
            if isinstance(r, GateRequest):
                self.hub.emit("gate.request", self.cycle, id=r.id, coop=coop, tool=tool, target=target, host=host,
                              status=r.status)
        if verdict == "deny":
            return Outcome(False, f"the gate refused: {r}")
        if verdict == "pending":
            return Outcome(False, f"waiting for the operator's approval as {r.id}. If approved it runs at the start of a "
                                  f"later cycle and you'll be told the result; don't ask again.", r.id)
        return self._execute_web(r)

    def _run_approved_web(self) -> None:
        """Requests you approved since last cycle: run them (outside the lock) and tell whoever asked."""
        with self.lock:
            todo = self.gate.approved()
        for r in todo:
            out = self._execute_web(r)
            with self.lock:
                self._tell(r.coop, "gate", f"{r.id} ran: {out.message[:700]}", r.id)

    def _execute_web(self, r: GateRequest):
        try:
            if r.tool == "web_search":
                results = self.web.search(r.target, k=5)
                text = "\n".join(f"- {x.title}: {x.url}\n  {x.snippet[:200]}" for x in results) or "no results"
                msg, ref = f"search results for {r.target!r} (web_fetch a url to read it):\n{text}", None
            else:
                page = self.web.fetch(r.target)
                with self.lock:
                    ids = self.archive.add_page(page.url, page.title, page.text, fetched=f"cycle {self.cycle}")
                    self.web_pages[r.target] = self.web_pages[page.url] = ids
                first = self.archive.get(ids[0]).text if ids else ""
                msg, ref = (f"read {page.url} ({page.title[:80]}) into the archive as {len(ids)} passage(s): "
                            f"{', '.join(ids[:12])}{' …' if len(ids) > 12 else ''}. Cite them as [archive: <id>]. The "
                            f"first:\n<untrusted>\n{first[:1500]}\n</untrusted>"), (ids[0] if ids else None)
            ok = True
        except WebError as e:
            msg, ref, ok = f"{r.tool} failed: {e}", None, False
        with self.lock:
            r.status, r.result = (RequestStatus.DONE if ok else RequestStatus.FAILED), msg[:300]
            self.hub.emit("web.call", self.cycle, id=r.id, coop=r.coop, tool=r.tool, target=r.target, ok=ok)
        return Outcome(ok, msg, ref)

    def _appraise_ventures(self) -> None:
        """Appraise waiting ventures outside the lock (a model call must never stall other communities),
        then decide under it: best score first, up to the market's budget for this cycle."""
        with self.lock:
            todo = [v for v in self.ventures.values() if v.status == VentureStatus.PENDING and v.score is None]
        def appraise(v):
            try:
                return v, self.appraiser.appraise(v)
            except AppraisalError as e:
                return v, e

        results = {}
        for v, a in self._map_calls(appraise, todo):
            if isinstance(a, AppraisalError):
                with self.lock:
                    self._tell(v.proposer, "venture_delayed", f"{v.id} couldn't be appraised yet: {a}", v.id)
            else:
                results[v.id] = a
        with self.lock:
            p = self.params
            for vid, a in results.items():
                v = self.ventures[vid]
                v.score, v.reason, v.reward = a.score, a.reason, venture_value(a.score, p.job_reward, p.venture_min_score)
                if a.cost:
                    payer = "treasury" if self.ledger.balance("treasury") >= a.cost else purse(v.proposer)
                    self.ledger.transfer(payer, "compute", min(a.cost, self.ledger.balance(payer)), cycle=self.cycle,
                                         kind="appraisal", memo=vid)
                if a.model and a.usage:
                    self.hub.emit("llm.call", self.cycle, community="appraiser", role="appraiser", model=a.model,
                                  input_tokens=a.usage.input_tokens, output_tokens=a.usage.output_tokens,
                                  cache_hit=None, cost=a.cost, ms=a.ms, real=a.real)
                    if a.real:
                        self.meter.record_real("appraiser", a.price_as or a.model, a.usage, cycle=self.cycle)
                if v.reward == 0:
                    self._decide_venture(v, approved=False)
            waiting = sorted((v for v in self.ventures.values() if v.status == VentureStatus.PENDING and v.score is not None),
                             key=lambda v: (-v.score, v.id))
            for i, v in enumerate(waiting):
                if i < p.venture_budget:
                    self._decide_venture(v, approved=True)
                else:
                    self._tell(v.proposer, "venture_waiting", f"{v.id} scored {v.score} but the market's budget this "
                               f"cycle went to better-scored ventures; it stays in line", v.id)

    def _decide_venture(self, v: Venture, approved: bool) -> None:
        if not approved:
            v.status = VentureStatus.REJECTED
            self._tell(v.proposer, "venture_rejected", f"{v.id} {v.title!r} rejected (score {v.score}): {v.reason}", v.id)
            self.hub.emit("venture.decided", self.cycle, id=v.id, proposer=v.proposer, title=v.title, status=VentureStatus.REJECTED,
                          score=v.score, reward=0, reason=v.reason)
            return
        self._venture_seq += 1
        job = MarketJob(f"V{self._venture_seq}", v.title, v.reward,
                        {c: Part(c, spec, rubric) for c, spec, rubric in v.parts}, posted=self.cycle,
                        deadline=self.cycle + self.params.job_ttl, prime=v.proposer, status=JobStatus.CLAIMED)
        self.jobs[job.id] = job
        v.status, v.job_id = VentureStatus.APPROVED, job.id
        self._tell(v.proposer, "venture_approved", f"{v.id} {v.title!r} approved as job {job.id}, reward {v.reward} µcr "
                   f"(score {v.score}: {v.reason}); deliver every part by cycle {job.deadline}", job.id)
        self.hub.emit("venture.decided", self.cycle, id=v.id, proposer=v.proposer, title=v.title, status=VentureStatus.APPROVED,
                      score=v.score, reward=v.reward, reason=v.reason, job=job.id)
        self.hub.emit("market.job", self.cycle, id=job.id, stage="venture", prime=v.proposer, caps=sorted(job.parts), reward=v.reward)

    def _charge_grade(self, g: Grade, *, job: str, part: str, payers: tuple[str, ...], audit: str | None = None) -> Grade:
        """Pay for one grade: the notional cost from the first payer that can afford it, and, if a billed
        model did the work, the real bill in USD as well. Under the lock."""
        if g.cost:
            payer = next((a for a in payers if self.ledger.balance(a) >= g.cost), payers[-1])
            self.ledger.transfer(payer, "compute", g.cost, cycle=self.cycle, kind="grading", memo=audit or job)
        if g.model and g.usage:
            self.hub.emit("llm.call", self.cycle, community="grader", role="grader", model=g.model,
                          input_tokens=g.usage.input_tokens, output_tokens=g.usage.output_tokens,
                          cache_hit=g.cache_hit, cost=g.cost, ms=g.ms, real=g.real)
            if g.real:
                self.meter.record_real("grader", g.price_as or g.model, g.usage, cycle=self.cycle)
        self.hub.emit("grader.grade", self.cycle, job=job, part=part, score=g.score, cost=g.cost, reason=g.reason,
                      model=g.model, real=g.real, **({"audit": audit} if audit else {}))
        return g

    def job_value(self, job: MarketJob) -> int:
        """What passing work is worth: its reward scaled by quality (`quality_pay`)."""
        q = self.params.quality_pay
        mean = sum(job.scores.values()) / len(job.scores) if job.scores else 1.0
        return round(job.reward * (1 - q + q * mean))

    def _fund_grants(self) -> None:
        """The funder tops the pool up by one budget, never beyond `grant_cap_cycles` budgets. Under the lock."""
        p = self.params
        if p.economy != "grant" or p.grant_budget <= 0:
            return
        room = p.grant_budget * p.grant_cap_cycles - self.ledger.balance("grants")
        if (amount := min(p.grant_budget, room)) > 0:
            self.ledger.transfer("funder", "grants", amount, cycle=self.cycle, kind="grant", memo="budget")

    def _award_grants(self) -> None:
        """Passing work shares the pool by value, never more than its value. Under the lock."""
        queue = [j for jid in self.grant_queue if (j := self.jobs.get(jid)) is not None and j.status == JobStatus.GRADED]
        self.grant_queue = []
        if not queue:
            return
        values = {j.id: self.job_value(j) for j in queue}
        pool, total = self.ledger.balance("grants"), sum(values.values())
        for j in sorted(queue, key=lambda j: j.id):
            share = values[j.id] if total <= pool else values[j.id] * pool // total
            j.status = JobStatus.CLAIMED
            self._pay_job(j, payout=share)
        self.hub.emit("grants.award", self.cycle, pool=pool, asked=total, paid=min(pool, total), jobs=len(queue))

    def _apply_ratings(self) -> None:
        """Your new ratings (commons/application/ratings.py): first-hand evidence about whoever did each part. Under the lock."""
        if not self.ratings:
            return
        for r in self.ratings.reload():
            sample = self.ratings.samples[r.id]
            for cap, part in sample["parts"].items():
                if part["by"] in self.communities:
                    self.rep.attest("operator", part["by"], cap, EVIDENCE[r.rating])
                    self._tell(part["by"], "rated", f"the operator rated your {cap} for {sample['job']} {r.rating}/3"
                               + (f": {r.note}" if r.note else ""), sample["job"])
            self.hub.emit("operator.rating", self.cycle, id=r.id, job=sample["job"], rating=r.rating, note=r.note)

    def _pay_job(self, job: MarketJob, payout: int | None = None) -> None:
        prime = job.prime
        weights: Counter[str] = Counter()
        for part in job.parts.values():
            for pid in part.cites:
                pb = self.library.get(pid)
                if pb and pb.author != prime and pb.author in self.communities:  # seeded playbooks earn no one royalties
                    weights[pb.author] += 1
                    pb.uses += 1
        # the commons takes only what it needs: no treasury share while the treasury is at its reserve
        tax = self.ledger.balance("treasury") < self.params.treasury_reserve
        mean = sum(job.scores.values()) / len(job.scores) if job.scores else 1.0
        if payout is None:
            payout = self.job_value(job)  # pay scales with quality
        grant = self.params.economy == "grant"
        split = self.ledger.settle_revenue(prime, payout, cycle=self.cycle, royalties=dict(weights), memo=job.id, tax=tax,
                                           source="grants" if grant else None)
        share = payout * (70 if tax else 90) // 100
        self._settle_bond(job, returned=True)
        job.status = JobStatus.PAID
        self.jobs_done += 1
        self._stat(prime, "earned", share)
        track = self.communities[prime].deliveries
        for cap, part in job.parts.items():
            if part.source == "self":
                track[cap] = track.get(cap, 0) + 1
        payer = "the grants paid" if grant else "the market paid"
        self._tell(prime, "job_paid", f"{job.id} passed grading (mean score {mean:.2f}); {payer} {payout} "
                   f"of {job.reward}, you received {share}", job.id)
        record = {"job": job.id, "title": job.title, "prime": prime, "cycle": self.cycle, "scores": dict(job.scores),
                  "payout": payout, "parts": {cap: {"by": self._done_by(job, part), "spec": part.spec,
                                                    "text": (part.artifact or "")[:4000]}
                                              for cap, part in sorted(job.parts.items())}}
        self.outputs.append(record)
        if self.ratings:
            self.ratings.sample(record)
        for author, amount in split.items():
            self._stat(author, "earned", amount)
            self.royalties_paid[author] = self.royalties_paid.get(author, 0) + amount
            self._tell(author, "royalty", f"your playbook was used in {job.id}: {amount}", job.id)
        self.hub.emit("market.job", self.cycle, id=job.id, stage="paid", prime=prime, caps=sorted(job.parts),
                      reward=job.reward, payout=payout, scores=job.scores, royalties=split, taxed=tax)

    def _done_by(self, job: MarketJob, part) -> str:
        if part.source in (None, "self"):
            return job.prime
        c = self.contracts.get(part.source)
        return c.winner if c and c.winner else job.prime

    def efficiency(self, name: str) -> dict[str, float]:
        """Value per unit of thought: what a co-op has earned against what it has spent to think (upkeep, work
        and model calls). Above 1.0 it earns more than its thinking costs."""
        earned = sum(s.earned for s in self.history.get(name, []))
        spent = self.meter.by_community.get(name, 0)
        return {"earned": earned, "spent": spent, "thinking": self.thinking_spend[name],
                "ratio": round(earned / spent, 3) if spent else 0.0}

    def held_jobs(self, name: str) -> int:
        return sum(j.prime == name and j.status == JobStatus.CLAIMED for j in self.jobs.values())

    def claim_limit(self, c: Community) -> int:
        return max(2, c.thinking)

    def pending_claims(self, name: str) -> list[str]:
        return [jid for jid, who in self.claims.items() if name in who]

    def _allocate_claims(self) -> None:
        """Give each claimed job to one claimant, by rule rather than by who answered first."""
        p = self.params
        for jid in sorted(self.claims):
            job, claimants = self.jobs.get(jid), self.claims.pop(jid)
            if job is None or job.status != JobStatus.OPEN:
                continue
            draw = random.Random(f"{p.seed}:{self.cycle}:{jid}")  # its own seed: the world's dice stay untouched

            def key(name: str) -> tuple:
                c = self.communities[name]
                fit = sum(cap in c.capabilities for cap in job.parts) / len(job.parts)
                return (-round(self._standing(name), 3), -fit, self.held_jobs(name), draw.random())

            bond = round(job.reward * p.claim_bond)
            for name in sorted(sorted(claimants), key=key):
                c = self.communities[name]
                if self.held_jobs(name) >= self.claim_limit(c):
                    continue
                if bond:
                    try:
                        self.ledger.transfer(purse(name), "escrow", bond, cycle=self.cycle, kind="bond", memo=jid)
                    except InsufficientFunds:
                        self._tell(name, "claim_lost", f"you couldn't post the {bond} bond for {jid}", jid)
                        continue
                job.prime, job.status, job.bond = name, JobStatus.CLAIMED, bond
                job.deadline = self.cycle + p.job_ttl
                self._tell(name, "claim_won", f"{jid} is yours (bond {bond}, returned when it's paid); "
                           f"submit every part by cycle {job.deadline}", jid)
                for other in claimants:
                    if other != name:
                        self._tell(other, "claim_lost", f"{jid} went to {name} (more trusted, a better fit, or less loaded)", jid)
                self.hub.emit("market.job", self.cycle, id=jid, stage="claimed", prime=name, caps=sorted(job.parts),
                              reward=job.reward, claimants=sorted(claimants), bond=bond)
                break

    def _settle_bond(self, job: MarketJob, returned: bool) -> None:
        if not job.bond:
            return
        dest = purse(job.prime) if returned else "treasury"
        self.ledger.transfer("escrow", dest, job.bond, cycle=self.cycle, kind="bond",
                             memo=f"{'return' if returned else 'forfeit'} {job.id}")
        job.bond = 0

    def _fail_job(self, job: MarketJob, why: str) -> None:
        self._settle_bond(job, returned=False)
        job.status = JobStatus.FAILED
        self.jobs_failed += 1
        for c in self.contracts.values():
            if c.job_id == job.id and c.status == ContractStatus.OPEN:
                self._close(c, ContractStatus.WITHDRAWN)
        self._tell(job.prime, "job_failed", f"{job.id} failed: {why}", job.id)
        self.hub.emit("market.job", self.cycle, id=job.id, stage="failed", prime=job.prime, caps=sorted(job.parts),
                      reward=job.reward, why=why)

    def add_playbook(self, pid: str, author: str, capability: str, title: str, text: str) -> None:
        self.library[pid] = Playbook(pid, author, capability, title, text)
        self.hub.emit("knowledge.publish", self.cycle, id=pid, author=author, capability=capability, title=title)

    # ── what a community sees ──────────────────────────────────
    def observe(self, me: Community) -> Observation:
        name, p = me.name, self.params
        pending = {(c.job_id, c.capability): c.status for c in self.contracts.values() if c.status in LIVE_CONTRACT}

        def job_view(j: MarketJob) -> JobView:
            return JobView(j.id, j.title, j.reward, tuple(
                PartView(cap, part.spec, part.rubric, part.artifact is not None, part.source, pending.get((j.id, cap)))
                for cap, part in sorted(j.parts.items())), j.deadline)

        def contract_view(c: Contract, as_prime: bool) -> ContractView:
            bids = tuple(BidView(b, price, round(self._trust(name, b, c.capability), 3), round(self._standing(b), 3),
                                 *self.eligible(name, b, c.capability))
                         for b, price in sorted(c.bids.items())) if as_prime else ()
            show = as_prime and c.status != ContractStatus.OPEN or c.winner == name
            return ContractView(c.id, c.job_id, c.capability, c.prime, c.spec, c.rubric, c.max_price, c.advance_frac,
                                c.announced, bids, c.bids.get(name), c.winner, c.price,
                                c.artifact if show else None, c.deadline, c.status)

        cs = self.contracts.values()
        return Observation(
            cycle=self.cycle, name=name, charter=me.charter, capabilities=tuple(sorted(me.capabilities)),
            members=me.members, funded=me.thinking, capacity=me.capacity,
            purse=self.ledger.balance(purse(name)), standing=round(self._standing(name), 3),
            board=tuple(job_view(j) for j in self.jobs.values() if j.status == JobStatus.OPEN),
            my_jobs=tuple(job_view(j) for j in self.jobs.values() if j.status == JobStatus.CLAIMED and j.prime == name),
            # a world rule: contracts the commons would refuse my bid on aren't offered at all
            open_contracts=tuple(contract_view(c, False) for c in cs
                                 if c.status == ContractStatus.OPEN and c.prime != name and self.eligible(c.prime, name, c.capability)[0]),
            refused_contracts=sum(1 for c in cs if c.status == ContractStatus.OPEN and c.prime != name and c.capability in me.capabilities
                                  and not self.eligible(c.prime, name, c.capability)[0]),
            claim_limit=max(2, me.thinking),
            my_announcements=tuple(contract_view(c, True) for c in cs if c.status == ContractStatus.OPEN and c.prime == name),
            to_deliver=tuple(contract_view(c, False) for c in cs if c.status == ContractStatus.AWARDED and c.winner == name),
            to_review=tuple(contract_view(c, True) for c in cs if c.status == ContractStatus.DELIVERED and c.prime == name
                            and not p.grader_reviews),
            to_attest=tuple(contract_view(c, False) for c in cs
                            if c.winner == name and c.closed is not None and c.status in (ContractStatus.ACCEPTED, ContractStatus.REJECTED, ContractStatus.FAILED)
                            and not c.winner_attested),
            peers=tuple(PeerView(o.name, tuple(sorted(o.capabilities)), o.members, round(self._standing(o.name), 3),
                                 {cap: round(self._trust(name, o.name, cap), 3) for cap in sorted(o.capabilities)})
                        for o in self._living() if o.name != name),
            spawn_requests=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role, round(self._standing(x.proposer), 3))
                                 for x in self.proposals.values()
                                 if x.kind == "spawn" and x.status == ProposalStatus.OPEN and x.proposer != name),
            merge_offers=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, "", round(self._standing(x.proposer), 3))
                               for x in self.proposals.values()
                               if x.kind == "merge" and x.status == ProposalStatus.OPEN and x.target == name),
            my_proposals=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role or x.target, 0.0)
                               for x in self.proposals.values() if x.proposer == name and x.status == ProposalStatus.OPEN),
            to_dispute=tuple(contract_view(c, False) for c in cs
                             if not p.grader_reviews and c.winner == name and c.status == ContractStatus.REJECTED and not c.disputed
                             and self.cycle <= c.closed + p.dispute_window),
            library=tuple(PlaybookView(pb.id, pb.capability, pb.author, pb.title, pb.uses) for pb in self.library.values()),
            events=tuple(self.inbox[name]),
            journal=tuple(self.journal[name]),
            params={"sub_share": p.sub_share, "work_cost": p.work_cost, "advance_frac": p.advance_frac, "publish_cost": p.publish_cost,
                    "spawn_fee": p.spawn_fee, "venture_fee": p.venture_fee, "learn_cost": p.learn_cost, "audit_cost": p.audit_cost,
                    "max_members": p.max_members, "pass_score": p.pass_score, "max_communities": p.max_communities,
                    "communities": len(self._living()),
                    "upkeep": p.upkeep, "actions_per_member": p.actions_per_member, "job_ttl": p.job_ttl},
            track=dict(me.deliveries),
            owed=sum(c.price - c.advance for c in cs if c.prime == name and c.status in (ContractStatus.AWARDED, ContractStatus.DELIVERED)),
            ventures=tuple(VentureView(v.id, v.title, v.status, v.score, v.reward, v.reason, v.job_id, v.cycle)
                           for v in list(self.ventures.values()) if v.proposer == name)[-5:],
            efficiency=self.efficiency(name),
            doctrine=me.doctrine,
            archive=(len(self.archive), tuple(sorted({p.source for p in self.archive.passages.values()}))),
            grants=(self.ledger.balance("grants"), self.params.grant_budget) if self.params.economy == "grant" else None,
            web=self.gate.policy.describe() if self.web else "",
            pending_claims=tuple(self.pending_claims(name)),
            goals=tuple(GoalView(g.id, g.title, g.status, tuple((s.text, s.done, s.note) for s in g.steps), round(g.progress, 2))
                        for g in self.plans[name].active()),
            ideas=tuple(IdeaView(i.id, i.title, i.detail, i.cycle, i.status) for i in self.plans[name].ideas[-5:]),
        )

    # ── gossip and records ─────────────────────────────────────
    def _gossip(self) -> None:
        for c in self._active():
            if not c.strategy.gossips:
                continue
            beliefs = sorted(self.rep.beliefs(c.name), key=lambda b: -b[3])[: self.params.gossip_fanout]
            for subject, cap, score, n in beliefs:
                self._send(c, Gossip(subject=subject, capability=cap, score=round(score, 4), evidence=round(n, 3)))
        # every community consumes the reputation stream through its own consumer group
        heard = 0
        for listener in self.communities.values():
            for env in self.bus.read("reputation", listener.name):
                if env.verb == "gossip":
                    g = env.open()
                    self.rep.hear(listener.name, env.sender, g.subject, g.capability, g.score, g.evidence)
                    heard += 1
        self.hub.emit("reputation.gossip", self.cycle, heard=heard)

    def _record(self) -> None:
        for name, c in self.communities.items():
            s = self._stats[name]
            self.history[name].append(Snapshot(
                cycle=self.cycle, purse=self.ledger.balance(purse(name)), standing=self._standing(name),
                allowance=self.bus.allowance(name), active=c.active, thinking=c.thinking,
                won=s["won"], delivered_ok=s["ok"], earned=s["earned"],
            ))
        self.scorecard = evaluate_scorecard(self, tuple(self.pack.scorecard) + GENERAL)
        for row in self.scorecard:
            if row["status"] == "breach":
                self.hub.emit("scorecard.breach", self.cycle, metric=row["key"], value=row["value"], floor=row["floor"])
        pipeline = Counter(c.status for c in self.contracts.values() if c.status in LIVE_CONTRACT)
        self.hub.emit(
            "world.cycle", self.cycle,
            treasury=self.ledger.balance("treasury"),
            jobs_done=self.jobs_done, jobs_failed=self.jobs_failed, jobs_expired=self.jobs_expired,
            board=sum(j.status == JobStatus.OPEN for j in self.jobs.values()),
            in_progress=sum(j.status == JobStatus.CLAIMED for j in self.jobs.values()),
            pipeline=dict(pipeline),
            grants=self.ledger.balance("grants") if self.params.economy == "grant" else None,
            scorecard={r["key"]: r["value"] for r in self.scorecard},
            bus_sent=dict(self.bus.sent),
            communities={
                n: {"purse": h[-1].purse, "standing": round(h[-1].standing, 4), "allowance": h[-1].allowance,
                    "active": h[-1].active, "thinking": h[-1].thinking, "won": h[-1].won,
                    "ok": h[-1].delivered_ok, "earned": h[-1].earned}
                for n, h in self.history.items()
            },
        )


def _default_ledger(p: Params, hub: Hub) -> Ledger:
    return Ledger(p.ledger_path, hub=hub)


def _default_bus(p: Params, hub: Hub) -> Bus:
    return MemoryBus(Registry(), base_allowance=p.base_allowance, verify=p.verify, hub=hub)


def _default_activity(p: Params) -> ActivityLog:
    return ActivityLog(p.activity_keep, p.activity_path)


def summary(world: World, window: int = 50) -> str:
    rows = [f"{'community':<10} {'strategy':<11} {'purse cr':>9} {'standing':>8} {'allow':>5} {'active%':>7} {'won':>5} {'ok':>5}"]
    for name, hist in world.history.items():
        c = world.communities[name]
        tail = hist[-window:]
        rows.append(
            f"{name:<10} {c.strategy.name:<11} {hist[-1].purse / 1e6:>9.3f} {hist[-1].standing:>8.3f} "
            f"{hist[-1].allowance:>5} {100 * sum(s.active for s in tail) / len(tail):>6.0f}% "
            f"{sum(s.won for s in hist):>5} {sum(s.delivered_ok for s in hist):>5}"
        )
    rows.append(f"jobs paid {world.jobs_done}, failed {world.jobs_failed}, expired on board {world.jobs_expired}, "
                f"treasury {world.ledger.balance('treasury') / 1e6:.3f} cr, playbooks {len(world.library)}, "
                f"royalties {sum(world.royalties_paid.values()) / 1e6:.3f} cr"
                + (f", grants left {world.ledger.balance('grants') / 1e6:.3f} cr" if world.params.economy == "grant" else ""))
    if world.scorecard:
        rows += ["", "scorecard", scorecard_report(world.scorecard)]
    return "\n".join(rows)
