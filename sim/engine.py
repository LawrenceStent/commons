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

Money in this world is created money (SIM credits); see substrate/ledger.py.
"""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field

from protocol import Envelope, Message
from protocol.reputation import Gossip
from sim.actions import Actions
from sim.grader import GradingError
from sim.market import CAPABILITIES, Grade, Grader, MarketJob, StubGrader, generate_job
from sim.population import Proposal, expire_proposals
from society.community import Community
from society.observation import (
    BidView, ContractView, Event, JobView, Observation, Outcome, PartView, PeerView, PlaybookView, ProposalView,
)
from society.strategies import Cooperator, Defector, FreeRider
from substrate.bus import MemoryBus, RateLimited
from substrate.ledger import InsufficientFunds, Ledger, purse
from substrate.meter import Meter
from substrate.registry import Registry
from substrate.reputation import Reputation
from substrate.telemetry import Hub

OPEN, AWARDED, DELIVERED = "open", "awarded", "delivered"
LIVE = (OPEN, AWARDED, DELIVERED)


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
    grade_retries: int = 3  # cycles a complete job waits for an unavailable grader before it fails
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
    retain: int = 20  # cycles a closed job or contract stays visible before it's dropped
    # population and capabilities (sim/population.py)
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
    """Twelve scripted agents in five communities."""
    return [
        Community("coop-a", 3, {"research", "build"}, Cooperator(), charter="research-led tools"),
        Community("coop-b", 3, {"build", "design"}, Cooperator(), charter="product studio"),
        Community("coop-c", 3, {"design", "write"}, Cooperator(), charter="content house"),
        Community("defector", 2, set(CAPABILITIES), Defector(), charter="we do everything"),
        Community("freerider", 1, {"write"}, FreeRider(), charter="-"),
    ]


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
    status: str = OPEN
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
                 hub: Hub | None = None, grader: Grader | None = None):
        self.params = p = params or Params()
        self.hub = hub or Hub()
        self.rng = random.Random(p.seed)
        self.cycle = 0
        self.communities = {c.name: c for c in (population or default_population())}
        self.ledger = Ledger(p.ledger_path, hub=self.hub)
        self.meter = Meter(self.ledger, daily_ceiling=p.daily_ceiling, hub=self.hub)
        self.rep = Reputation(decay=p.decay, hub=self.hub)
        self.registry = Registry()
        self.bus = MemoryBus(self.registry, standing=self._standing, base_allowance=p.base_allowance,
                             verify=p.verify, hub=self.hub)
        self.grader = grader or StubGrader(cost=p.grade_cost)
        self.jobs: dict[str, MarketJob] = {}
        self.contracts: dict[str, Contract] = {}
        self.library: dict[str, Playbook] = {}
        self.journal: dict[str, deque[str]] = {n: deque(maxlen=p.journal_keep) for n in self.communities}
        self.inbox: dict[str, deque[Event]] = {n: deque(maxlen=p.events_keep) for n in self.communities}
        self.history: dict[str, list[Snapshot]] = {n: [] for n in self.communities}
        self.jobs_done = self.jobs_failed = self.jobs_expired = 0
        self.royalties_paid: dict[str, int] = {}
        self.proposals: dict[str, Proposal] = {}
        self.awaiting_grade: dict[str, int] = {}  # job id -> failed grading attempts
        self.known_capabilities = set(CAPABILITIES).union(*(c.capabilities for c in self.communities.values()))
        self._job_seq = self._proposal_seq = 0
        self._stats: dict[str, Counter] = {}

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
        self.cycle += 1
        self.rep.cycle = self.cycle
        self.bus.begin_cycle(self.cycle)
        self._stats = {n: Counter() for n in self.communities}
        self._floor()
        self._upkeep()
        self._deadlines()
        expire_proposals(self)
        self._post_jobs()
        order = self._active()
        self.rng.shuffle(order)  # turn order must not decide who wins
        for c in order:
            self._turn(c)
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
            job = generate_job(self.rng, f"J{self._job_seq}", self.cycle, p.job_reward, p.board_ttl, p.parts_per_job)
            self.jobs[job.id] = job
            self.hub.emit("market.job", self.cycle, id=job.id, stage="posted", caps=sorted(job.parts), reward=job.reward)

    def _turn(self, c: Community) -> None:
        obs = self.observe(c)
        self.inbox[c.name].clear()
        c.strategy.turn(obs, Actions(self, c))

    # ── deadlines ──────────────────────────────────────────────
    def _deadlines(self) -> None:
        now = self.cycle
        for job in self.jobs.values():
            if job.status == "open" and now > job.deadline:
                job.status = "expired"
                self.jobs_expired += 1
                self.hub.emit("market.job", now, id=job.id, stage="expired", caps=sorted(job.parts), reward=job.reward)
            elif job.status == "claimed" and now > job.deadline and job.id not in self.awaiting_grade:
                self._fail_job(job, "missed its deadline")
        for jid in list(self.awaiting_grade):
            job = self.jobs.get(jid)
            if job is None or job.status != "claimed":
                self.awaiting_grade.pop(jid, None)
            elif self.awaiting_grade[jid] >= self.params.grade_retries:
                self.awaiting_grade.pop(jid)
                self._fail_job(job, "the grader was unavailable")
            else:
                self.maybe_submit(job)
        for c in list(self.contracts.values()):
            if c.deadline >= now:
                continue
            if c.status == OPEN:
                self._close(c, "expired")
                self._tell(c.prime, "expired", f"{c.id} closed with no award", c.id)
            elif c.status == AWARDED:
                # non-delivery is objective: the substrate files the prime's complaint for it
                self._close(c, "failed")
                self.rep.attest(c.prime, c.winner, c.capability, 0.0)
                self._tell(c.prime, "failed", f"{c.winner} never delivered {c.id}", c.id)
                self._tell(c.winner, "failed", f"you missed the delivery deadline on {c.id}", c.id)
            elif c.status == DELIVERED:
                if self.pay_remainder(c):
                    self.close_review(c, True, "accepted by default: the prime didn't review in time")
                else:
                    self._close(c, "defaulted")
                    self.rep.attest(c.winner, c.prime, c.capability, 0.0)
                    c.winner_attested = True
                    self._tell(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)

    def _close(self, c: Contract, status: str) -> None:
        c.status, c.closed = status, self.cycle
        self._stage(c, status)

    def _prune(self) -> None:
        """Drop closed jobs and contracts after a while, so memory stays flat on long runs."""
        cutoff = self.cycle - self.params.retain
        for k in [k for k, j in self.jobs.items() if j.status not in ("open", "claimed") and j.deadline < cutoff]:
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
        self._stage(c, OPEN)

    def award_contract(self, c: Contract, bidder: str, price: int, advance: int) -> None:
        c.status, c.winner, c.price, c.advance = AWARDED, bidder, price, advance
        c.deadline = self.cycle + self.params.deliver_ttl
        self._stat(bidder, "won")
        self._stat(bidder, "earned", advance)
        self._tell(bidder, "awarded", f"you won {c.id} at {price}; advance {advance} paid; deliver by cycle {c.deadline}", c.id)
        for loser in c.bids:
            if loser != bidder:
                self._tell(loser, "bid_lost", f"{c.id} went to another bidder", c.id)
        self._stage(c, AWARDED)

    def deliver_contract(self, c: Contract, artifact: str, cites: tuple[str, ...]) -> None:
        c.status, c.artifact, c.cites = DELIVERED, artifact, cites
        c.deadline = self.cycle + self.params.review_ttl
        self._tell(c.prime, "delivered", f"{c.winner} delivered {c.id}; review by cycle {c.deadline}", c.id)
        self._stage(c, DELIVERED)

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
        self._close(c, "accepted" if accept else "rejected")
        self.rep.attest(c.prime, c.winner, c.capability, 1.0 if accept else 0.0)
        if accept:
            self._stat(c.winner, "ok")
            track = self.communities[c.winner].deliveries
            track[c.capability] = track.get(c.capability, 0) + 1
            self._tell(c.winner, "accepted", f"{c.prime} accepted {c.id} and paid {c.price - c.advance}", c.id)
            job = self.jobs.get(c.job_id)
            if job and job.status == "claimed" and job.parts[c.capability].artifact is None:
                part = job.parts[c.capability]
                part.artifact, part.source, part.cites = c.artifact, c.id, c.cites
                self.maybe_submit(job)
        else:
            self._tell(c.winner, "rejected", f"{c.prime} rejected {c.id}: {reason or 'no reason given'}", c.id)

    def audit(self, c: Contract, reason: str) -> Outcome:
        """Grade a disputed delivery. The commons ("audit") files its own first-hand evidence,
        so the verdict moves standing, not any one community's private view."""
        p = self.params
        try:
            g = self._grade(c.spec, c.rubric, c.artifact or "", job=c.job_id, part=c.capability,
                            payers=("treasury", purse(c.winner)), audit=c.id)
        except GradingError as e:
            self.ledger.transfer("treasury", purse(c.winner), p.audit_cost, cycle=self.cycle, kind="audit", memo=f"refund {c.id}")
            return Outcome(False, f"the grader is unavailable ({e}); your fee was refunded, try again next turn")
        c.disputed = True
        if g.score < p.pass_score:
            self.rep.attest("audit", c.winner, c.capability, 0.0)
            self._stage(c, "audit_upheld", score=g.score)
            self._tell(c.prime, "audit", f"the audit upheld your rejection of {c.id} ({g.score:.2f})", c.id)
            return Outcome(False, f"the audit upheld the rejection: your delivery scored {g.score:.2f}; the fee is gone")
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
            self._close(c, "defaulted")
            self._tell(c.winner, "audit", f"the audit found for you on {c.id}, but {c.prime} can't pay", c.id)
            return Outcome(True, f"the audit found for you ({g.score:.2f}), but {c.prime} can't pay; it is recorded as a default")
        self._stat(c.winner, "earned", owed + p.audit_cost)
        self._stat(c.winner, "ok")
        c.reason = f"overturned on audit ({g.score:.2f}): {reason}"
        self._close(c, "accepted")
        self._stage(c, "audit_overturned", score=g.score)
        self._tell(c.prime, "audit", f"the audit overturned your rejection of {c.id}; you paid {owed} plus the {p.audit_cost} fee", c.id)
        job = self.jobs.get(c.job_id)
        if job and job.status == "claimed" and job.parts[c.capability].artifact is None:
            part = job.parts[c.capability]
            part.artifact, part.source, part.cites = c.artifact, c.id, c.cites
            self.maybe_submit(job)
        return Outcome(True, f"the audit found for you ({g.score:.2f}): {c.prime} paid {owed} plus your {p.audit_cost} fee")

    def maybe_submit(self, job: MarketJob) -> None:
        """A complete job goes to the grader. Every part must pass for the market to pay."""
        if not job.complete or job.status != "claimed":
            return
        for cap, part in job.parts.items():
            if cap in job.scores:
                continue  # graded on an earlier attempt
            try:
                # the commons pays for grading; when it can't, the prime whose job it is does
                g = self._grade(part.spec, part.rubric, part.artifact, job=job.id, part=cap,
                                payers=("treasury", purse(job.prime)))
            except GradingError as e:
                self.awaiting_grade[job.id] = self.awaiting_grade.get(job.id, 0) + 1
                self._tell(job.prime, "grading_delayed", f"{job.id} is waiting for the grader: {e}", job.id)
                return
            except InsufficientFunds:
                self._fail_job(job, "no one could pay for grading")
                return
            job.scores[cap] = g.score
        self.awaiting_grade.pop(job.id, None)
        if min(job.scores.values()) < self.params.pass_score:
            self._fail_job(job, f"a part failed grading ({', '.join(f'{k} {v:.2f}' for k, v in job.scores.items())})")
            return
        self._pay_job(job)

    def _grade(self, spec: str, rubric: str, artifact: str, *, job: str, part: str, payers: tuple[str, ...],
               audit: str | None = None) -> Grade:
        """Grade one part and pay for it: the notional cost from the first payer that can
        afford it, and, if a billed model did the work, the real bill in USD as well."""
        g = self.grader.grade(spec, rubric, artifact)
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

    def _pay_job(self, job: MarketJob) -> None:
        prime = job.prime
        weights: Counter[str] = Counter()
        for part in job.parts.values():
            for pid in part.cites:
                pb = self.library.get(pid)
                if pb and pb.author != prime:
                    weights[pb.author] += 1
                    pb.uses += 1
        # the commons takes only what it needs: no treasury share while the treasury is at its reserve
        tax = self.ledger.balance("treasury") < self.params.treasury_reserve
        split = self.ledger.settle_revenue(prime, job.reward, cycle=self.cycle, royalties=dict(weights), memo=job.id, tax=tax)
        share = job.reward * (70 if tax else 90) // 100
        job.status = "paid"
        self.jobs_done += 1
        self._stat(prime, "earned", share)
        track = self.communities[prime].deliveries
        for cap, part in job.parts.items():
            if part.source == "self":
                track[cap] = track.get(cap, 0) + 1
        self._tell(prime, "job_paid", f"{job.id} passed grading; you received {share}", job.id)
        for author, amount in split.items():
            self._stat(author, "earned", amount)
            self.royalties_paid[author] = self.royalties_paid.get(author, 0) + amount
            self._tell(author, "royalty", f"your playbook was used in {job.id}: {amount}", job.id)
        self.hub.emit("market.job", self.cycle, id=job.id, stage="paid", prime=prime, caps=sorted(job.parts),
                      reward=job.reward, scores=job.scores, royalties=split, taxed=tax)

    def _fail_job(self, job: MarketJob, why: str) -> None:
        job.status = "failed"
        self.jobs_failed += 1
        for c in self.contracts.values():
            if c.job_id == job.id and c.status == OPEN:
                self._close(c, "withdrawn")
        self._tell(job.prime, "job_failed", f"{job.id} failed: {why}", job.id)
        self.hub.emit("market.job", self.cycle, id=job.id, stage="failed", prime=job.prime, caps=sorted(job.parts),
                      reward=job.reward, why=why)

    def add_playbook(self, pid: str, author: str, capability: str, title: str, text: str) -> None:
        self.library[pid] = Playbook(pid, author, capability, title, text)
        self.hub.emit("knowledge.publish", self.cycle, id=pid, author=author, capability=capability, title=title)

    # ── what a community sees ──────────────────────────────────
    def observe(self, me: Community) -> Observation:
        name, p = me.name, self.params
        pending = {(c.job_id, c.capability): c.status for c in self.contracts.values() if c.status in LIVE}

        def job_view(j: MarketJob) -> JobView:
            return JobView(j.id, j.title, j.reward, tuple(
                PartView(cap, part.spec, part.rubric, part.artifact is not None, part.source, pending.get((j.id, cap)))
                for cap, part in sorted(j.parts.items())), j.deadline)

        def contract_view(c: Contract, as_prime: bool) -> ContractView:
            bids = tuple(BidView(b, price, round(self._trust(name, b, c.capability), 3), round(self._standing(b), 3))
                         for b, price in sorted(c.bids.items())) if as_prime else ()
            show = as_prime and c.status != OPEN or c.winner == name
            return ContractView(c.id, c.job_id, c.capability, c.prime, c.spec, c.rubric, c.max_price, c.advance_frac,
                                c.announced, bids, c.bids.get(name), c.winner, c.price,
                                c.artifact if show else None, c.deadline, c.status)

        cs = self.contracts.values()
        return Observation(
            cycle=self.cycle, name=name, charter=me.charter, capabilities=tuple(sorted(me.capabilities)),
            members=me.members, funded=me.thinking, capacity=me.capacity,
            purse=self.ledger.balance(purse(name)), standing=round(self._standing(name), 3),
            board=tuple(job_view(j) for j in self.jobs.values() if j.status == "open"),
            my_jobs=tuple(job_view(j) for j in self.jobs.values() if j.status == "claimed" and j.prime == name),
            open_contracts=tuple(contract_view(c, False) for c in cs if c.status == OPEN and c.prime != name),
            my_announcements=tuple(contract_view(c, True) for c in cs if c.status == OPEN and c.prime == name),
            to_deliver=tuple(contract_view(c, False) for c in cs if c.status == AWARDED and c.winner == name),
            to_review=tuple(contract_view(c, True) for c in cs if c.status == DELIVERED and c.prime == name),
            to_attest=tuple(contract_view(c, False) for c in cs
                            if c.winner == name and c.closed is not None and c.status in ("accepted", "rejected", "failed")
                            and not c.winner_attested),
            peers=tuple(PeerView(o.name, tuple(sorted(o.capabilities)), o.members, round(self._standing(o.name), 3),
                                 {cap: round(self._trust(name, o.name, cap), 3) for cap in sorted(o.capabilities)})
                        for o in self._living() if o.name != name),
            spawn_requests=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role, round(self._standing(x.proposer), 3))
                                 for x in self.proposals.values()
                                 if x.kind == "spawn" and x.status == "open" and x.proposer != name),
            merge_offers=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, "", round(self._standing(x.proposer), 3))
                               for x in self.proposals.values()
                               if x.kind == "merge" and x.status == "open" and x.target == name),
            my_proposals=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role or x.target, 0.0)
                               for x in self.proposals.values() if x.proposer == name and x.status == "open"),
            to_dispute=tuple(contract_view(c, False) for c in cs
                             if c.winner == name and c.status == "rejected" and not c.disputed
                             and self.cycle <= c.closed + p.dispute_window),
            library=tuple(PlaybookView(pb.id, pb.capability, pb.author, pb.title, pb.uses) for pb in self.library.values()),
            events=tuple(self.inbox[name]),
            journal=tuple(self.journal[name]),
            params={"sub_share": p.sub_share, "work_cost": p.work_cost, "advance_frac": p.advance_frac, "publish_cost": p.publish_cost,
                    "spawn_fee": p.spawn_fee, "learn_cost": p.learn_cost, "audit_cost": p.audit_cost,
                    "max_members": p.max_members, "pass_score": p.pass_score, "max_communities": p.max_communities,
                    "communities": len(self._living()),
                    "upkeep": p.upkeep, "actions_per_member": p.actions_per_member, "job_ttl": p.job_ttl, "pass_score": p.pass_score},
            track=dict(me.deliveries),
            owed=sum(c.price - c.advance for c in cs if c.prime == name and c.status in (AWARDED, DELIVERED)),
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
        pipeline = Counter(c.status for c in self.contracts.values() if c.status in LIVE)
        self.hub.emit(
            "world.cycle", self.cycle,
            treasury=self.ledger.balance("treasury"),
            jobs_done=self.jobs_done, jobs_failed=self.jobs_failed, jobs_expired=self.jobs_expired,
            board=sum(j.status == "open" for j in self.jobs.values()),
            in_progress=sum(j.status == "claimed" for j in self.jobs.values()),
            pipeline=dict(pipeline),
            bus_sent=dict(self.bus.sent),
            communities={
                n: {"purse": h[-1].purse, "standing": round(h[-1].standing, 4), "allowance": h[-1].allowance,
                    "active": h[-1].active, "thinking": h[-1].thinking, "won": h[-1].won,
                    "ok": h[-1].delivered_ok, "earned": h[-1].earned}
                for n, h in self.history.items()
            },
        )


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
                f"royalties {sum(world.royalties_paid.values()) / 1e6:.3f} cr")
    return "\n".join(rows)
