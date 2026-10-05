"""The society: its state, and the facade the rest of the code talks to.

A society holds its co-ops, jobs, contracts, library, plans and records, and the infrastructure it runs on (ledger,
bus, meter, reputation, telemetry). Its work is done by services, one responsibility each:

    board         jobs posted, claimed (allocated by rule at cycle end), finished, failed    services/board.py
    contract_net  parts bought from other co-ops: bids, awards, deliveries, audits           services/contract_net.py
    grading       submitted work, deliveries and audits judged; the citation rule           services/grading.py
    payments      passing work paid as the economy says; paid work recorded                services/payments.py
    venture_desk  co-ops' own proposals appraised, priced and approved                       services/ventures.py
    web_desk      web reads behind the gate                                                  services/web.py
    upkeep        the floor and waking members                                               services/upkeep.py
    rating_desk   your ratings applied as evidence                                           services/ratings.py
    gossip        co-ops relay what they've seen                                             services/gossip.py
    recorder      tallies, snapshots, the scorecard, cycle telemetry                         services/recorder.py
    observer      what a co-op sees                                                          observe.py

One cycle runs them in a fixed order (commons/application/cycle.py). Agents act only through the actions executor
(commons/application/actions.py). Money in a simulated society is created money (SIM credits); see
commons/substrate/ledger.py.
"""

from __future__ import annotations

import random
import threading
from collections import Counter, defaultdict, deque

from commons.application import saving
from commons.application.actions import Actions
from commons.application.cycle import run_cycle
from commons.application.events import Events
from commons.application.gate import Gate
from commons.application.observation import (
    Event,
    Observation,
)
from commons.application.observe import ObservationBuilder
from commons.application.operator import Operator
from commons.application.params import Params
from commons.application.ports import WebPort
from commons.application.ratings import Ratings
from commons.application.services.approvals import Approvals
from commons.application.services.board import JobBoard
from commons.application.services.contract_net import ContractNet
from commons.application.services.gossip import GossipService
from commons.application.services.grading import Grading
from commons.application.services.payments import Payments
from commons.application.services.ratings import RatingDesk
from commons.application.services.recorder import Recorder, Snapshot
from commons.application.services.upkeep import Upkeep
from commons.application.services.ventures import VentureDesk
from commons.application.services.web import WebDesk
from commons.domain import events as ev
from commons.domain.archive import ArchiveIndex
from commons.domain.community import Community
from commons.domain.contract import Contract
from commons.domain.desk import Desk
from commons.domain.economy import PaymentPolicy, policy_for
from commons.domain.goals import Plans
from commons.domain.grading import Grader, StubGrader
from commons.domain.ids import Sequences
from commons.domain.knowledge import Playbook
from commons.domain.market import MarketJob
from commons.domain.pack import Pack
from commons.domain.pack import load as load_pack
from commons.domain.population import Proposal
from commons.domain.reputation import Reputation
from commons.domain.ventures import Appraiser, StubAppraiser, Venture
from commons.protocol import Envelope, Message
from commons.substrate.activity import ActivityLog
from commons.substrate.bus import Bus, MemoryBus, RateLimited
from commons.substrate.ledger import Ledger, purse
from commons.substrate.meter import Meter
from commons.substrate.registry import Registry
from commons.substrate.telemetry import Hub



def _last_two() -> deque:
    return deque(maxlen=2)

class Society:
    def __init__(self, params: Params | None = None, population: list[Community] | None = None,
                 hub: Hub | None = None, grader: Grader | None = None, appraiser: Appraiser | None = None,
                 operator: Operator | None = None, pack: Pack | None = None, archive: ArchiveIndex | None = None,
                 ratings: Ratings | None = None, web: WebPort | None = None, gate: Gate | None = None,
                 ledger: Ledger | None = None, bus: Bus | None = None, activity: ActivityLog | None = None,
                 payment: PaymentPolicy | None = None, desk: Desk | None = None):
        """Everything outside the society's rules can be passed in (the model-backed grader and appraiser, the web,
        the ledger, the bus, the activity log, the economy, the pack's desk); what isn't is built from `params`."""
        self.params = p = params or Params()
        self.pack = pack or load_pack()  # what this society is for: its work, vocabulary and seed co-ops
        self.hub = hub or Hub()
        self.lock = threading.RLock()  # held for every state change; see cycle.py
        self.rng = random.Random(p.run.seed)
        self.cycle = 0
        self.communities = {c.name: c for c in (population or self.pack.population())}
        self.desk = desk or (self.pack.desk(p.run.seed) if self.pack.desk else None)  # the pack's own tools (domain/desk.py)
        self._connect(ledger, bus, grader, appraiser, operator, archive, ratings, web, gate, payment)
        self._open_records()
        self.activity = activity or ActivityLog(p.storage.activity_keep, p.storage.activity_path)
        self.activity.watch(self.hub)
        self._start_services()
        self._genesis()

    def _connect(self, ledger, bus, grader, appraiser, operator, archive, ratings, web, gate, payment) -> None:
        """The infrastructure and collaborators: given, or the defaults."""
        p = self.params
        self.ledger = ledger or Ledger(p.storage.ledger_path, hub=self.hub)
        self.meter = Meter(self.ledger, daily_ceiling=p.money.daily_ceiling, hub=self.hub)
        self.rep = Reputation(decay=p.trust.decay, emit=self.hub.emit)
        self.bus = bus or MemoryBus(Registry(), base_allowance=p.trust.base_allowance, verify=p.run.verify, hub=self.hub)
        self.bus.standing = self.standing  # the bus rations messages by this society's trust
        self.registry = self.bus.registry
        self.operator = operator or Operator(None)
        if self.desk:
            self.operator.know(t["name"] for t in self.desk.tools)
        self.archive = archive or ArchiveIndex()  # the society's reference material, searched on demand
        self.ratings = ratings  # your ratings of a sample of the paid work (commons/application/ratings.py)
        self.gate = gate or Gate()
        self.gate.policy = self.operator.gate
        self.attach(grader, appraiser, web)
        # how passing work is paid: given, or chosen once from the settings
        self.payment = payment or policy_for(p.money.economy, p.money.grant_budget, p.money.grant_cap_cycles)

    def attach(self, grader=None, appraiser=None, web: WebPort | None = None) -> None:
        """What judges work, and the web (a WebPort; None = no web at all), behind the gate whose policy is the
        operator's [gate] section: given, or the defaults. Also used when a saved society resumes."""
        self.grader = grader or StubGrader(cost=self.params.market.grade_cost)
        self.appraiser = appraiser or StubAppraiser()
        self.web = web
        if self.web:
            self.web.set_hosts(self.gate.policy.allow_hosts)

    def _open_records(self) -> None:
        """The society's state: work, knowledge, plans, and what happened."""
        p = self.params
        self.outputs: deque[dict] = deque(maxlen=p.storage.outputs_keep)  # paid work, newest last: who did what, how it scored
        self.scorecard: list[dict] = []  # the pack's mission metrics plus the general ones, as of the last cycle
        self.ventures: dict[str, Venture] = {}
        self.jobs: dict[str, MarketJob] = {}
        self.contracts: dict[str, Contract] = {}
        self.library: dict[str, Playbook] = {}
        self.journal: dict[str, deque[str]] = {n: deque(maxlen=p.storage.journal_keep) for n in self.communities}
        self.inbox: dict[str, deque[Event]] = {n: deque(maxlen=p.storage.events_keep) for n in self.communities}
        self.history: dict[str, list[Snapshot]] = {n: [] for n in self.communities}
        self.jobs_done = self.jobs_failed = self.jobs_expired = 0
        self.royalties_paid: dict[str, int] = {}
        self.proposals: dict[str, Proposal] = {}
        self.thinking_spend: Counter[str] = Counter()  # µcr of model calls, per co-op
        self.cheapest_call: dict[str, int] = {}  # µcr of each co-op's cheapest steward call so far
        self.transcripts: defaultdict[str, deque] = defaultdict(_last_two)  # LLM turns, newest last
        self.plans: defaultdict[str, Plans] = defaultdict(Plans)  # ideas and goals per community
        self.known_capabilities = set(self.pack.capabilities).union(*(c.capabilities for c in self.communities.values()))
        self.turn_order: list[Community] = []  # this cycle's, shuffled (see cycle.py)

    def _start_services(self) -> None:
        """The world's work, one responsibility each (commons/application/services/)."""
        self.events = Events(self)  # domain events, and what co-ops are told and telemetry records of them
        self.observer = ObservationBuilder(self)
        self.recorder = Recorder(self)
        self.gossip = GossipService(self)
        self.upkeep = Upkeep(self)
        self.web_desk = WebDesk(self)
        self.approvals = Approvals(self)
        self.rating_desk = RatingDesk(self)
        self.payments = Payments(self)
        self.venture_desk = VentureDesk(self)
        self.ids = Sequences()  # numbered ids: jobs, ventures, ideas and goals, proposals
        self.board = JobBoard(self)
        self.contract_net = ContractNet(self)
        self.grading = Grading(self)

    def _genesis(self) -> None:
        """Money in at the start: the treasury's seed and every co-op's purse; each co-op registers its key."""
        p = self.params
        self.ledger.transfer("genesis", "treasury", p.money.treasury_seed, cycle=0, kind="genesis")
        for c in self.communities.values():
            c.strategy.rng = random.Random(f"{p.run.seed}:{c.name}")
            self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
            self.ledger.transfer("genesis", purse(c.name), p.money.purse_seed, cycle=0, kind="genesis")

    def add_community(self, c: Community) -> None:
        """A community born mid-run (a fork). Its history starts empty, not back-filled."""
        p = self.params
        self.communities[c.name] = c
        self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
        self.journal[c.name] = deque(maxlen=p.storage.journal_keep)
        self.inbox[c.name] = deque(maxlen=p.storage.events_keep)
        self.history[c.name] = []
        self.recorder.track(c.name)

    # ── helpers ────────────────────────────────────────────────
    def standing(self, name: str) -> float:
        return self.rep.standing(name) if self.params.run.reputation else 0.5

    def eligible(self, prime: str, bidder: str, capability: str) -> tuple[bool, str]:
        """Whether the commons lets `bidder` work for `prime` in `capability`. Deterministic; with
        reputation switched off (the control run) everyone is neutral and eligible."""
        floor = self.params.contracts.bid_floor
        standing = self.standing(bidder)
        if standing < floor:
            return False, f"{bidder}'s standing in the commons is {standing:.2f}, below the {floor:.2f} line"
        trust = self.trust(prime, bidder, capability)
        if trust < floor:
            return False, f"{prime}'s record of {bidder} in {capability} is {trust:.2f}, below the {floor:.2f} line"
        return True, ""

    def trust(self, observer: str, subject: str, capability: str) -> float:
        return self.rep.score(observer, subject, capability) if self.params.run.reputation else 0.5

    def tell(self, name: str, kind: str, text: str, ref: str | None = None) -> None:
        self.inbox[name].append(Event(self.cycle, kind, text, ref))

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

    def run(self, cycles: int) -> Society:
        for _ in range(cycles):
            self.step()
        return self

    # ── saving and resuming (commons/application/saving.py) ──
    def save(self, path) -> None:
        saving.save(self, path)

    @classmethod
    def resume(cls, path, **attach) -> Society:
        return saving.resume(path, **attach)

    def __getstate__(self) -> dict:
        return saving.state_of(self)

    def __setstate__(self, state: dict) -> None:
        saving.restore(self, state)

    def turn(self, c: Community) -> None:
        with self.lock:
            obs = self.observe(c)
            self.inbox[c.name].clear()
        c.strategy.turn(obs, Actions(self, c))

    # ── deadlines ──────────────────────────────────────────────

    # ── called by the actions executor ────────────────────────

    # ── the web, behind the gate ───────────────────────────────

    def observe(self, me: Community) -> Observation:
        """What a co-op sees (commons/application/observe.py)."""
        return self.observer.build(me)

    def add_playbook(self, pid: str, author: str, capability: str, title: str, text: str) -> None:
        self.library[pid] = Playbook(pid, author, capability, title, text)
        self.events.publish(ev.PlaybookPublished(self.library[pid]))

    # ── what a community sees ──────────────────────────────────

    # ── gossip and records ─────────────────────────────────────

World = Society  # the name the code grew up with; both mean the same class
