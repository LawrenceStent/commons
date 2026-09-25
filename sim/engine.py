"""The Phase 0 world: scripted communities, a mock market, and the real substrate.

One cycle:
    floor     treasury pays every community the flat basic budget
    upkeep    each community pays compute for its members to think; can't pay => silent
    market    jobs arrive, each needing two capabilities; one community takes each as prime
    contract  the prime buys capabilities it lacks: announce -> bid -> award -> deliver -> settle
    revenue   finished jobs pay out 70/20/10 (prime / treasury / cited playbooks)
    knowledge communities publish playbooks for what they do well
    gossip    communities relay first-hand beliefs; everyone listens
    decay     old evidence fades
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from protocol import Envelope, Message
from protocol.contract import Announce, Award, Bid, Deliver, Settle
from protocol.knowledge import Cite, Publish
from protocol.reputation import Attest, Gossip
from society.community import Community
from society.strategies import Cooperator, Defector, FreeRider, Job, Strategy
from substrate.bus import MemoryBus, RateLimited
from substrate.ledger import InsufficientFunds, Ledger, purse
from substrate.meter import Meter
from substrate.registry import Registry
from substrate.reputation import Reputation
from substrate.telemetry import Hub

CAPABILITIES = ("research", "build", "design", "write")


@dataclass
class Params:
    seed: int = 0
    reputation: bool = True  # False = the control run: primes can't tell bidders apart
    treasury_seed: int = 2_000_000
    purse_seed: int = 150_000
    basic_budget: int = 6_000  # flat, per community, per cycle
    upkeep: int = 8_000  # per member, per cycle
    actions_per_member: int = 2
    jobs_per_cycle: int = 4
    job_reward: int = 150_000
    sub_share: float = 0.4  # of job reward offered for each subcontracted capability
    advance_frac: float = 0.5
    publish_cost: int = 15_000
    gossip_every: int = 5
    gossip_fanout: int = 3
    base_allowance: int = 12
    decay: float = 0.995
    daily_ceiling: int = 10**12
    verify: bool = True
    ledger_path: str = ":memory:"  # a file under runs/ keeps long runs out of RAM


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
    uses: int = 0


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


class _View:
    """What a strategy is allowed to see. Scores respect the reputation switch."""

    def __init__(self, world: World, me: Community):
        self.world, self.me = world, me
        self.rng = world.rng
        self.cycle = world.cycle

    def balance(self) -> int:
        return self.world.ledger.balance(purse(self.me.name))

    def score(self, subject: str, capability: str) -> float:
        if not self.world.params.reputation:
            return 0.5
        return self.world.rep.score(self.me.name, subject, capability)

    def standing(self, subject: str) -> float:
        return self.world._standing(subject)

    def playbook_for(self, capability: str) -> str | None:
        pbs = self.world.library.get(capability)
        return pbs[0].id if pbs else None

    def authored(self, capability: str) -> bool:
        return any(p.author == self.me.name for p in self.world.library.get(capability, []))


class World:
    def __init__(self, params: Params | None = None, population: list[Community] | None = None, hub: Hub | None = None):
        self.params = p = params or Params()
        self.hub = hub or Hub()
        self.rng = random.Random(p.seed)
        self.cycle = 0
        self.communities = {c.name: c for c in (population or default_population())}
        self.ledger = Ledger(p.ledger_path, hub=self.hub)
        self.meter = Meter(self.ledger, daily_ceiling=p.daily_ceiling, hub=self.hub)
        self.rep = Reputation(decay=p.decay, hub=self.hub)
        self.registry = Registry()
        self.bus = MemoryBus(
            self.registry,
            standing=self._standing,
            base_allowance=p.base_allowance,
            verify=p.verify,
            hub=self.hub,
        )
        self.library: dict[str, list[Playbook]] = {}
        self.history: dict[str, list[Snapshot]] = {n: [] for n in self.communities}
        self.jobs_done = self.jobs_failed = 0
        self.royalties_paid: dict[str, int] = {}  # author -> total, since the start
        self._cycle_stats: dict[str, dict[str, int]] = {}

        self.ledger.transfer("genesis", "treasury", p.treasury_seed, cycle=0, kind="genesis")
        for c in self.communities.values():
            self.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
            self.ledger.transfer("genesis", purse(c.name), p.purse_seed, cycle=0, kind="genesis")

    # ── helpers ────────────────────────────────────────────────
    def _standing(self, name: str) -> float:
        return self.rep.standing(name) if self.params.reputation else 0.5

    def _send(self, c: Community, msg: Message) -> bool:
        try:
            self.bus.publish(Envelope.seal(c.identity, msg, self.cycle))
            return True
        except RateLimited:
            return False

    def _view(self, c: Community) -> _View:
        return _View(self, c)

    def _stat(self, name: str, key: str, n: int = 1) -> None:
        self._cycle_stats[name][key] += n

    def _charge(self, c: Community, amount: int, memo: str) -> bool:
        try:
            self.meter.charge(c.name, amount, cycle=self.cycle, memo=memo)
            return True
        except InsufficientFunds:
            return False

    def _pay(self, src: Community, dst: Community, amount: int, memo: str) -> bool:
        try:
            self.ledger.transfer(purse(src.name), purse(dst.name), amount, cycle=self.cycle, kind="contract", memo=memo)
            return True
        except InsufficientFunds:
            return False

    def _active(self) -> list[Community]:
        return [c for c in self.communities.values() if c.active]

    # ── the cycle ──────────────────────────────────────────────
    def step(self) -> None:
        self.cycle += 1
        self.bus.begin_cycle(self.cycle)
        self._cycle_stats = {n: {"won": 0, "ok": 0, "earned": 0} for n in self.communities}
        start = {n: self.ledger.balance(purse(n)) for n in self.communities}

        self._floor()
        self._upkeep()
        for job_caps in self._market():
            self._run_job(*job_caps)
        self._knowledge()
        if self.cycle % self.params.gossip_every == 0:
            self._gossip()
        self.rep.tick()
        self.bus.compact()
        self._record(start)

    def run(self, cycles: int) -> World:
        for _ in range(cycles):
            self.step()
        return self

    def _floor(self) -> None:
        for c in self.communities.values():
            if self.ledger.balance("treasury") < self.params.basic_budget:
                return
            self.ledger.transfer("treasury", purse(c.name), self.params.basic_budget, cycle=self.cycle, kind="floor")

    def _upkeep(self) -> None:
        """Fund as many members as the purse allows. None funded means silence."""
        for c in self.communities.values():
            c.thinking = min(c.members, self.ledger.balance(purse(c.name)) // self.params.upkeep)
            if c.thinking and not self._charge(c, c.thinking * self.params.upkeep, "upkeep"):
                c.thinking = 0
            c.active = c.thinking > 0
            c.capacity = c.thinking * self.params.actions_per_member

    def _market(self) -> list[tuple[Community, tuple[str, str], int]]:
        taken = []
        for _ in range(self.params.jobs_per_cycle):
            caps = tuple(self.rng.sample(CAPABILITIES, 2))
            takers = [
                c for c in self._active()
                if c.capacity and c.strategy.take_market_job(c, caps, self.params.job_reward, self.params.sub_share, self._view(c))
            ]
            if takers:
                prime = self.rng.choice(takers)
                prime.capacity -= 1
                taken.append((prime, caps, self.params.job_reward))
        return taken

    def _run_job(self, prime: Community, caps: tuple[str, str], reward: int) -> None:
        job_id = hashlib.sha256(f"{self.cycle}:{self.rng.random()}".encode()).hexdigest()[:12]
        cites: list[str] = []
        ok = True
        # secure the parts we can't do before spending on the parts we can
        for cap in sorted(caps, key=prime.can):
            if prime.can(cap):
                work = prime.strategy.work(prime, cap, self._view(prime))
                if not self._charge(prime, work.cost, f"work {job_id}"):
                    ok = False
                    break
                ok = ok and work.quality >= 0.5
                if ok:
                    prime.deliveries[cap] = prime.deliveries.get(cap, 0) + 1
                cites += work.cites
            else:
                done, sub_cites = self._subcontract(prime, Job(f"{job_id}.{cap}", cap, round(reward * self.params.sub_share), self.params.advance_frac))
                ok = ok and done
                cites += sub_cites
            if not ok:
                break

        if not ok:
            self.jobs_failed += 1
            self.hub.emit("market.job", self.cycle, id=job_id, prime=prime.name, caps=list(caps), reward=reward, status="failed")
            return
        self.jobs_done += 1
        royalties: dict[str, int] = {}
        for pid in cites:
            pb = self._playbook(pid)
            if pb and pb.author != prime.name:
                royalties[pb.author] = royalties.get(pb.author, 0) + 1
                pb.uses += 1
        split = self.ledger.settle_revenue(prime.name, reward, cycle=self.cycle, royalties=royalties, memo=job_id)
        self._stat(prime.name, "earned", reward * 70 // 100)
        for author, amount in split.items():
            self._stat(author, "earned", amount)
            self.royalties_paid[author] = self.royalties_paid.get(author, 0) + amount
        self.hub.emit("market.job", self.cycle, id=job_id, prime=prime.name, caps=list(caps), reward=reward,
                      status="paid", royalties=split)

    def _contract_event(self, prime: Community, job: Job, stage: str, bids: list[tuple[str, int]] = (), **kw) -> None:
        self.hub.emit("contract.closed", self.cycle, id=job.job_id, capability=job.capability, prime=prime.name,
                      max_price=job.reward, bids=dict(bids), stage=stage, **kw)

    def _subcontract(self, prime: Community, job: Job) -> tuple[bool, list[str]]:
        if not self._send(prime, Announce(job_id=job.job_id, capability=job.capability,
                                          reward=job.reward, advance_frac=self.params.advance_frac)):
            self._contract_event(prime, job, "rate_limited")
            return False, []

        bids: list[tuple[str, int]] = []
        bidders = self._active()
        self.rng.shuffle(bidders)  # arrival order must not decide ties
        for c in bidders:
            if c is prime or not c.capacity:
                continue
            price = c.strategy.bid(c, job, self._view(c))
            if price and price <= job.reward and self._send(c, Bid(job_id=job.job_id, price=price)):
                c.capacity -= 1
                bids.append((c.name, price))

        winner_name = prime.strategy.choose(prime, job, bids, self._view(prime))
        for bidder, _ in bids:
            c = self.communities[bidder]
            c.strategy.on_bid_result(c, bidder == winner_name)
        if winner_name is None:
            self._contract_event(prime, job, "no_award", bids)
            return False, []
        winner = self.communities[winner_name]
        price = dict(bids)[winner_name]
        advance = round(price * self.params.advance_frac)
        if not self._pay(prime, winner, advance, f"advance {job.job_id}"):
            self._contract_event(prime, job, "unfunded", bids, winner=winner_name, price=price)
            return False, []
        self._send(prime, Award(job_id=job.job_id, winner=winner.name, price=price, advance=advance))
        self._stat(winner.name, "won")
        self._stat(winner.name, "earned", advance)

        work = winner.strategy.work(winner, job.capability, self._view(winner))
        if not self._charge(winner, work.cost, f"work {job.job_id}"):
            work = type(work)(quality=0.0, cost=0)  # couldn't afford to think: nothing delivered
        self._send(winner, Deliver(job_id=job.job_id, artifact={"quality": round(work.quality, 3)},
                                   cites=list(work.cites)))
        for pid in work.cites:
            self._send(winner, Cite(playbook_id=pid, job_id=job.job_id))

        accepted = prime.strategy.accept(prime, work.quality)
        paid = 0
        if accepted and self._pay(prime, winner, price - advance, f"settle {job.job_id}"):
            paid = price - advance
            self._stat(winner.name, "ok")
            self._stat(winner.name, "earned", paid)
            winner.deliveries[job.capability] = winner.deliveries.get(job.capability, 0) + 1
        elif accepted:
            accepted = False  # prime couldn't pay; the job fails and the winner will say so
        self._send(prime, Settle(job_id=job.job_id, accepted=accepted, paid=paid))
        self._contract_event(prime, job, "accepted" if accepted else "rejected", bids, winner=winner.name,
                             price=price, advance=advance, paid=paid, quality=round(work.quality, 3), cites=list(work.cites))

        self._attest(prime, winner, job, prime.strategy.attest(prime, 1.0 if work.quality >= 0.5 else 0.0))
        self._attest(winner, prime, job, winner.strategy.attest(winner, 1.0 if paid or work.quality < 0.5 else 0.0))
        return accepted, list(work.cites)

    def _attest(self, observer: Community, subject: Community, job: Job, outcome: float) -> None:
        self._send(observer, Attest(job_id=job.job_id, subject=subject.name, capability=job.capability, outcome=outcome))
        self.rep.attest(observer.name, subject.name, job.capability, outcome)

    def _playbook(self, pid: str) -> Playbook | None:
        for pbs in self.library.values():
            for pb in pbs:
                if pb.id == pid:
                    return pb
        return None

    def _knowledge(self) -> None:
        for c in self._active():
            cap = c.strategy.publish(c, self._view(c))
            if cap is None or not self.meter.can_afford(c.name, self.params.publish_cost):
                continue
            pid = hashlib.sha256(f"{c.name}:{cap}".encode()).hexdigest()[:10]
            if not self._send(c, Publish(playbook_id=pid, capability=cap, title=f"{c.name} on {cap}", content_hash=pid)):
                continue
            self._charge(c, self.params.publish_cost, f"publish {pid}")
            self.library.setdefault(cap, []).append(Playbook(pid, c.name, cap))
            self.hub.emit("knowledge.publish", self.cycle, id=pid, author=c.name, capability=cap)
            if c.workspace:
                c.workspace.write(f"playbooks/{pid}.md", f"# {c.name} on {cap}\n")

    def _gossip(self) -> None:
        for c in self._active():
            if not c.strategy.gossips(c):
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

    def _record(self, start: dict[str, int]) -> None:
        for name, c in self.communities.items():
            s = self._cycle_stats[name]
            self.history[name].append(Snapshot(
                cycle=self.cycle,
                purse=self.ledger.balance(purse(name)),
                standing=self._standing(name),
                allowance=self.bus.allowance(name),
                active=c.active,
                thinking=c.thinking,
                won=s["won"],
                delivered_ok=s["ok"],
                earned=s["earned"],
            ))
        self.hub.emit(
            "world.cycle", self.cycle,
            treasury=self.ledger.balance("treasury"),
            jobs_done=self.jobs_done, jobs_failed=self.jobs_failed,
            bus_sent=dict(self.bus.sent),
            communities={
                n: {"purse": h[-1].purse, "standing": round(h[-1].standing, 4), "allowance": h[-1].allowance,
                    "active": h[-1].active, "thinking": h[-1].thinking, "won": h[-1].won,
                    "ok": h[-1].delivered_ok, "earned": h[-1].earned}
                for n, h in self.history.items()
            },
        )


def summary(world: World, window: int = 50) -> str:
    rows = [f"{'community':<10} {'strategy':<11} {'purse $':>9} {'standing':>8} {'allow':>5} {'active%':>7} {'won':>5} {'ok':>5}"]
    for name, hist in world.history.items():
        c = world.communities[name]
        tail = hist[-window:]
        rows.append(
            f"{name:<10} {c.strategy.name:<11} {hist[-1].purse / 1e6:>9.3f} {hist[-1].standing:>8.3f} "
            f"{hist[-1].allowance:>5} {100 * sum(s.active for s in tail) / len(tail):>6.0f}% "
            f"{sum(s.won for s in hist):>5} {sum(s.delivered_ok for s in hist):>5}"
        )
    rows.append(f"jobs done {world.jobs_done}, failed {world.jobs_failed}, treasury ${world.ledger.balance('treasury') / 1e6:.3f}, "
                f"playbooks {sum(len(v) for v in world.library.values())}")
    return "\n".join(rows)
