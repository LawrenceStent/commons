"""How a scripted community spends its turn.

A strategy sees an `Observation` and acts only through the `ActionsAPI`: the executor signs,
publishes, moves money and records outcomes, so no strategy can reach around the substrate.
The LLM runtime implements the same `turn(obs, act)`; these scripted characters are the
regression suite it gets measured against.

The base class is the honest default; scripted strategies override the hooks where they differ.
"""

from __future__ import annotations

import random

from commons.agents.waking import free, members_to_wake
from commons.application.observation import ActionsAPI, BidView, ContractView, JobView, Observation
from commons.domain.grading import StubGrader, is_tagged, tagged
from commons.domain.money import Micros
from commons.domain.status import ContractStatus

_read = StubGrader()


def quality_of(artifact: str | None) -> float:
    """What a scripted reviewer sees when it inspects a delivery."""
    return _read.grade("", "", artifact or "").score


class Strategy:
    name = "base"
    gossips = True

    def __init__(self, work_cost: Micros | None = None, markup: float = 1.6, refuse_below: float = 0.35,
                 explore: float = 0.1, max_jobs: int = 2, publish_after: int = 5):
        self.work_cost = work_cost
        self.markup = markup
        self.refuse_below = refuse_below
        # Without exploration an unknown bidder never beats an incumbent with a track
        # record, and the market crystallizes around whoever got lucky first.
        self.explore = explore
        self.max_jobs = max_jobs
        self.publish_after = publish_after
        self.rng = random.Random(0)  # the world reseeds this per community

    # ── the turn ───────────────────────────────────────────────
    def turn(self, obs: Observation, act: ActionsAPI) -> None:
        """Obligations first (reviews, deliveries, ratings), then new business."""
        self.learn(obs)
        for c in obs.to_review:
            self.review(obs, act, c)
        for c in obs.to_deliver:
            self.deliver(obs, act, c)
        for c in obs.to_dispute:
            self.dispute(obs, act, c)
        for c in obs.to_attest:
            self.rate(obs, act, c)
        for c in obs.my_announcements:
            self.award(obs, act, c)
        self.claim(obs, act)
        for job in obs.my_jobs:
            self.work_job(obs, act, job)
        for c in obs.open_contracts:
            self.bid(obs, act, c)
        self.publish(obs, act)
        self.grow(obs, act)

    def wake(self, obs: Observation) -> int:
        """How many members to pay to think this cycle (commons/agents/waking.py), at this strategy's own costs."""
        return members_to_wake(obs, self.cost)

    # ── hooks ──────────────────────────────────────────────────
    def learn(self, obs: Observation) -> None:
        """Competition sets margins: drift up after a win, down after a loss, never below cost."""
        for e in obs.events:
            if e.kind == "awarded":
                self.markup = min(2.0, self.markup * 1.02)
            elif e.kind == "bid_lost":
                self.markup = max(1.1, self.markup * 0.98)

    def review(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        # Scripted characters can only read quality tags. Real (untagged) work from an LLM contractor
        # is accepted: the prime already chose to trust this bidder, and the grader judges the job.
        ok = quality_of(c.artifact) >= 0.5 if is_tagged(c.artifact) else True
        act.review(c.id, ok, "" if ok else "below the rubric")

    def deliver(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if obs.capacity and act.spend(self.cost(obs, c.capability), f"work {c.id}"):
            act.deliver(c.id, self.artifact(obs, c.capability), self.cites(obs, c.capability))

    def rate(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        """Truthfully: a prime that paid, or fairly rejected bad work, was a good counterparty."""
        fair = (c.status in (ContractStatus.ACCEPTED, ContractStatus.FAILED)
                or (c.status == ContractStatus.REJECTED and is_tagged(c.artifact) and quality_of(c.artifact) < 0.5))
        act.attest(c.id, 1.0 if fair else 0.0)

    def award(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if c.announced >= obs.cycle or not c.bids:
            return
        pick = self.choose(c, c.bids)
        # the announcement already counted as promised in free(); the award must still be payable in full
        price = next((b.price for b in c.bids if b.bidder == pick), 0)
        if pick and obs.purse - obs.owed >= price:
            act.award(c.id, pick)

    def choose(self, c: ContractView, bids: tuple[BidView, ...]) -> str | None:
        """Refuse anyone we don't trust; usually take the best expected value, sometimes explore."""
        ok = [b for b in bids if b.trust >= self.refuse_below and b.standing >= self.refuse_below]
        if not ok:
            return None
        if self.rng.random() < self.explore:
            return self.rng.choice(ok).bidder
        return max(ok, key=lambda b: b.trust - 0.5 * b.price / c.max_price).bidder

    def claim(self, obs: Observation, act: ActionsAPI) -> None:
        """Take a job only if we can do part of it and finance all of it from the purse."""
        if len(obs.my_jobs) >= max(self.max_jobs, obs.funded) or obs.capacity < 2:
            return
        sub_share = obs.params.get("sub_share", 0.4)
        for job in obs.board:
            if not any(c in obs.capabilities for c in job.capabilities):
                continue
            need = sum(self.cost(obs, c) if c in obs.capabilities else job.reward * sub_share for c in job.capabilities)
            if self.free(obs) >= 1.5 * need:
                act.claim(job.id)
                return

    def work_job(self, obs: Observation, act: ActionsAPI, job: JobView) -> None:
        """Buy the parts we can't do before spending on the parts we can, so a job we can't
        finish doesn't eat our own work too."""
        sub_share = obs.params.get("sub_share", 0.4)
        advance = obs.params.get("advance_frac", 0.5)
        mine = [p for p in job.parts if p.capability in obs.capabilities]
        theirs = [p for p in job.parts if p.capability not in obs.capabilities]
        for p in theirs:
            if not p.done and p.pending is None:
                act.announce(job.id, p.capability, round(job.reward * sub_share), advance)
        if all(p.done or p.pending in ("awarded", "delivered") for p in theirs):
            for p in mine:
                if not p.done and obs.capacity and act.spend(self.cost(obs, p.capability), f"work {job.id}"):
                    act.do_part(job.id, p.capability, self.artifact(obs, p.capability), self.cites(obs, p.capability))

    def bid(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if c.capability not in obs.capabilities or c.my_bid is not None or obs.capacity < 2:
            return
        cost = self.cost(obs, c.capability)
        price = round(cost * self.markup)
        upkeep = int(obs.params.get("upkeep", 8_000))
        # never promise work we can't fund, counting a member awake to do it
        if price <= c.max_price and self.free(obs) + price * c.advance_frac >= cost + upkeep:
            act.bid(c.id, price)

    def publish(self, obs: Observation, act: ActionsAPI) -> None:
        """Write up a method once we've done something enough times to know it works."""
        mine = {p.capability for p in obs.library if p.author == obs.name}
        for cap in sorted(obs.capabilities):
            if obs.track.get(cap, 0) >= self.publish_after and cap not in mine:
                act.publish(cap, f"{obs.name} on {cap}", f"How {obs.name} does {cap}: check the rubric line by line before sending.")
                return

    def dispute(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        """Contest a rejection only when we know the work was good: a lost audit costs the fee and standing."""
        if quality_of(c.artifact) >= obs.params.get("pass_score", 0.5) and obs.purse >= obs.params.get("audit_cost", 0):
            act.dispute(c.id, "the delivery meets the rubric")

    def grow(self, obs: Observation, act: ActionsAPI) -> None:
        """Vouch for trusted peers; add members while there's more work than hands; pivot
        into thin markets; split off once full. All only from money that isn't promised."""
        for r in obs.spawn_requests:
            if r.standing >= 0.6:
                act.second_spawn(r.id)
        for m in obs.merge_offers:
            if m.standing >= 0.6:
                act.accept_merge(m.id)
        p, free = obs.params, self.free(obs)
        upkeep = int(p.get("upkeep", 4_000))
        busy = len(obs.my_jobs) >= max(self.max_jobs, obs.funded) and len(obs.board) >= 2
        if (busy and obs.members < p.get("max_members", 7) and not obs.my_proposals
                and free >= p.get("spawn_fee", 300_000) + 50 * upkeep):
            act.propose_spawn("worker")
            return
        # pivot out of a crowded niche; don't collect capabilities (that ends trade)
        thin = self.thin_market(obs) if len(obs.capabilities) < 3 else None
        if thin and free >= 3 * p.get("learn_cost", 500_000):
            act.learn(thin, self.playbook(obs, thin))
            return
        if (obs.members >= p.get("max_members", 7) and p.get("communities", 0) < p.get("max_communities", 12)
                and free >= 4 * p.get("spawn_fee", 300_000)):
            n = 1 + sum(peer.name.startswith(obs.name + "-") for peer in obs.peers)
            act.fork(f"{obs.name}-{n}", obs.members // 2, obs.capabilities, f"split from {obs.name}")

    def thin_market(self, obs: Observation) -> str | None:
        """A capability we lack that at most one trusted peer offers, when ours are crowded."""
        providers = lambda c: sum(c in peer.capabilities and peer.standing >= 0.6 for peer in obs.peers)
        if min((providers(c) for c in obs.capabilities), default=0) < 2:
            return None  # our niche isn't crowded
        known = {c for peer in obs.peers for c in peer.capabilities} - set(obs.capabilities)
        thin = {c: providers(c) for c in known if providers(c) <= 1}
        return min(sorted(thin), key=thin.get) if thin else None

    # ── money ──────────────────────────────────────────────────
    def free(self, obs: Observation) -> int:
        return free(obs, self.cost)

    # ── the work itself ────────────────────────────────────────
    def playbook(self, obs: Observation, capability: str) -> str | None:
        for p in obs.library:
            if p.capability == capability:
                return p.id
        return None

    def cites(self, obs: Observation, capability: str) -> tuple[str, ...]:
        pb = self.playbook(obs, capability)
        return (pb,) if pb else ()

    def cost(self, obs: Observation, capability: str) -> int:
        base = self.work_cost or int(obs.params.get("work_cost", 25_000))
        return round(base * (0.7 if self.playbook(obs, capability) else 1.0))

    def quality(self, obs: Observation, capability: str) -> float:
        q = self.rng.uniform(0.7, 1.0)
        if self.rng.random() < 0.05:  # honest mistakes happen
            q = self.rng.uniform(0.2, 0.5)
        return min(1.0, q + 0.05) if self.playbook(obs, capability) else q

    def artifact(self, obs: Observation, capability: str) -> str:
        return tagged(self.quality(obs, capability), f" {capability} by {obs.name}")
