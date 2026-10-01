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

How passing work is paid is the economy's business (`Params.economy`, a policy from commons/domain/economy.py):
a market pays each passing job at once; grants share a fixed pool among the cycle's passing work by value.

Money in this world is created money (SIM credits); see commons/substrate/ledger.py.
"""

from __future__ import annotations

import random
import threading
from collections import Counter, defaultdict, deque
from dataclasses import dataclass

from commons.application.actions import Actions
from commons.application.cycle import run_cycle
from commons.application.gate import Gate
from commons.application.observation import (
    BidView,
    ContractView,
    Event,
    GoalView,
    IdeaView,
    JobView,
    Observation,
    PartView,
    PeerView,
    PlaybookView,
    ProposalView,
    VentureView,
)
from commons.application.operator import Operator
from commons.application.params import Params
from commons.application.population import Proposal
from commons.application.ports import WebPort
from commons.application.ratings import Ratings
from commons.application.services.board import JobBoard
from commons.application.services.contract_net import ContractNet
from commons.application.services.grading import Grading
from commons.application.services.payments import Payments
from commons.application.services.ratings import RatingDesk
from commons.application.services.upkeep import Upkeep
from commons.application.services.ventures import VentureDesk
from commons.application.services.web import WebDesk
from commons.domain.archive import ArchiveIndex
from commons.domain.community import Community
from commons.domain.contract import Contract
from commons.domain.economy import PaymentPolicy, policy_for
from commons.domain.goals import Plans
from commons.domain.grading import Grader, StubGrader
from commons.domain.ids import Sequences
from commons.domain.knowledge import Playbook
from commons.domain.market import MarketJob
from commons.domain.pack import Pack
from commons.domain.pack import load as load_pack
from commons.domain.scorecard import GENERAL
from commons.domain.scorecard import evaluate as evaluate_scorecard
from commons.domain.scorecard import report as scorecard_report
from commons.domain.status import (
    LIVE_CONTRACT,
    ContractStatus,
    JobStatus,
    ProposalStatus,
)
from commons.domain.ventures import Appraiser, StubAppraiser, Venture
from commons.protocol import Envelope, Message
from commons.protocol.reputation import Gossip
from commons.substrate.activity import ActivityLog
from commons.substrate.bus import Bus, MemoryBus, RateLimited
from commons.substrate.ledger import Ledger, purse
from commons.substrate.meter import Meter
from commons.substrate.registry import Registry
from commons.substrate.reputation import Reputation
from commons.substrate.telemetry import Hub


def default_population() -> list[Community]:
    """The default pack's scripted co-ops (kept for callers that predate packs)."""
    return load_pack().population()


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
                 ledger: Ledger | None = None, bus: Bus | None = None, activity: ActivityLog | None = None,
                 payment: PaymentPolicy | None = None):
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
        self.bus.standing = self.standing  # the bus rations messages by this society's trust
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
        self.outputs: deque[dict] = deque(maxlen=p.outputs_keep)  # paid work, newest last: who did what, how it scored
        # how passing work is paid: given, or chosen once from the settings
        self.payment = payment or policy_for(p.economy, p.grant_budget, p.grant_cap_cycles)
        self.scorecard: list[dict] = []  # the pack's mission metrics plus the general ones, as of the last cycle
        self.ventures: dict[str, Venture] = {}
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
        self.thinking_spend: Counter[str] = Counter()  # µcr of model calls, per co-op
        self.transcripts: defaultdict[str, deque] = defaultdict(lambda: deque(maxlen=2))  # LLM turns, newest last
        self.plans: defaultdict[str, Plans] = defaultdict(Plans)  # ideas and goals per community
        self.activity = activity or _default_activity(p)
        self.activity.watch(self.hub)
        self.upkeep = Upkeep(self)
        self.web_desk = WebDesk(self)
        self.rating_desk = RatingDesk(self)
        self.payments = Payments(self)
        self.venture_desk = VentureDesk(self)
        self.ids = Sequences()  # numbered ids: jobs, ventures, ideas and goals, proposals
        self.board = JobBoard(self)
        self.contract_net = ContractNet(self)
        self.grading = Grading(self)
        self.known_capabilities = set(self.pack.capabilities).union(*(c.capabilities for c in self.communities.values()))
        self._stats: dict[str, Counter] = {n: Counter() for n in self.communities}
        self.turn_order: list[Community] = []  # this cycle's, shuffled (see cycle.py)

        self.ledger.transfer("genesis", "treasury", p.treasury_seed, cycle=0, kind="genesis")
        for c in self.communities.values():
            c.strategy.rng = random.Random(f"{p.seed}:{c.name}")
            self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
            self.ledger.transfer("genesis", purse(c.name), p.purse_seed, cycle=0, kind="genesis")

    def add_community(self, c: Community) -> None:
        """A community born mid-run (a fork). Its history starts empty, not back-filled."""
        p = self.params
        self.communities[c.name] = c
        self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
        self.journal[c.name] = deque(maxlen=p.journal_keep)
        self.inbox[c.name] = deque(maxlen=p.events_keep)
        self.history[c.name] = []
        self._stats[c.name] = Counter()

    # ── helpers ────────────────────────────────────────────────
    def standing(self, name: str) -> float:
        return self.rep.standing(name) if self.params.reputation else 0.5

    def eligible(self, prime: str, bidder: str, capability: str) -> tuple[bool, str]:
        """Whether the commons lets `bidder` work for `prime` in `capability`. Deterministic; with
        reputation switched off (the control run) everyone is neutral and eligible."""
        floor = self.params.bid_floor
        standing = self.standing(bidder)
        if standing < floor:
            return False, f"{bidder}'s standing in the commons is {standing:.2f}, below the {floor:.2f} line"
        trust = self._trust(prime, bidder, capability)
        if trust < floor:
            return False, f"{prime}'s record of {bidder} in {capability} is {trust:.2f}, below the {floor:.2f} line"
        return True, ""

    def _trust(self, observer: str, subject: str, capability: str) -> float:
        return self.rep.score(observer, subject, capability) if self.params.reputation else 0.5

    def tell(self, name: str, kind: str, text: str, ref: str | None = None) -> None:
        self.inbox[name].append(Event(self.cycle, kind, text, ref))

    def stat(self, name: str, key: str, n: int = 1) -> None:
        self._stats[name][key] += n

    def send(self, c: Community, msg: Message) -> bool:
        try:
            self.bus.publish(Envelope.seal(c.identity, msg, self.cycle))
            return True
        except RateLimited:
            return False

    def active(self) -> list[Community]:
        return [c for c in self.communities.values() if c.active and not c.dissolved]

    def living(self) -> list[Community]:
        return [c for c in self.communities.values() if not c.dissolved]

    # ── the cycle ──────────────────────────────────────────────
    def step(self) -> None:
        """One cycle, phase by phase (commons/application/cycle.py)."""
        run_cycle(self)

    def run(self, cycles: int) -> World:
        for _ in range(cycles):
            self.step()
        return self

    def turn(self, c: Community) -> None:
        with self.lock:
            obs = self.observe(c)
            self.inbox[c.name].clear()
        c.strategy.turn(obs, Actions(self, c))

    # ── deadlines ──────────────────────────────────────────────

    # ── called by the actions executor ────────────────────────

    # ── the web, behind the gate ───────────────────────────────

    def efficiency(self, name: str) -> dict[str, float]:
        """Value per unit of thought: what a co-op has earned against what it has spent to think (upkeep, work
        and model calls). Above 1.0 it earns more than its thinking costs."""
        earned = sum(s.earned for s in self.history.get(name, []))
        spent = self.meter.by_community.get(name, 0)
        return {"earned": earned, "spent": spent, "thinking": self.thinking_spend[name],
                "ratio": round(earned / spent, 3) if spent else 0.0}

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
            bids = tuple(BidView(b, price, round(self._trust(name, b, c.capability), 3), round(self.standing(b), 3),
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
            purse=self.ledger.balance(purse(name)), standing=round(self.standing(name), 3),
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
            peers=tuple(PeerView(o.name, tuple(sorted(o.capabilities)), o.members, round(self.standing(o.name), 3),
                                 {cap: round(self._trust(name, o.name, cap), 3) for cap in sorted(o.capabilities)})
                        for o in self.living() if o.name != name),
            spawn_requests=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role, round(self.standing(x.proposer), 3))
                                 for x in self.proposals.values()
                                 if x.kind == "spawn" and x.status == ProposalStatus.OPEN and x.proposer != name),
            merge_offers=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, "", round(self.standing(x.proposer), 3))
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
                    "communities": len(self.living()),
                    "upkeep": p.upkeep, "actions_per_member": p.actions_per_member, "job_ttl": p.job_ttl},
            track=dict(me.deliveries),
            owed=sum(c.owed for c in cs if c.prime == name and c.status in (ContractStatus.AWARDED, ContractStatus.DELIVERED)),
            ventures=tuple(VentureView(v.id, v.title, v.status, v.score, v.reward, v.reason, v.job_id, v.cycle)
                           for v in list(self.ventures.values()) if v.proposer == name)[-5:],
            efficiency=self.efficiency(name),
            doctrine=me.doctrine,
            archive=(len(self.archive), tuple(sorted({p.source for p in self.archive.passages.values()}))),
            grants=self.payment.view(self.payments.pool_balance()),
            web=self.gate.policy.describe() if self.web else "",
            pending_claims=tuple(self.board.pending_claims(name)),
            goals=tuple(GoalView(g.id, g.title, g.status, tuple((s.text, s.done, s.note) for s in g.steps), round(g.progress, 2))
                        for g in self.plans[name].active()),
            ideas=tuple(IdeaView(i.id, i.title, i.detail, i.cycle, i.status) for i in self.plans[name].ideas[-5:]),
        )

    # ── gossip and records ─────────────────────────────────────
    def _gossip(self) -> None:
        for c in self.active():
            if not c.strategy.gossips:
                continue
            beliefs = sorted(self.rep.beliefs(c.name), key=lambda b: -b[3])[: self.params.gossip_fanout]
            for subject, cap, score, n in beliefs:
                self.send(c, Gossip(subject=subject, capability=cap, score=round(score, 4), evidence=round(n, 3)))
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
                cycle=self.cycle, purse=self.ledger.balance(purse(name)), standing=self.standing(name),
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
            grants=self.payments.pool_balance() if self.payment.pool else None,
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
                + (f", grants left {world.payments.pool_balance() / 1e6:.3f} cr" if world.payment.pool else ""))
    if world.scorecard:
        rows += ["", "scorecard", scorecard_report(world.scorecard)]
    return "\n".join(rows)
