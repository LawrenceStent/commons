"""How a scripted community spends its turn.

A strategy sees an `Observation` and acts only through the `ActionsAPI`: the executor signs,
publishes, moves money and records outcomes, so no strategy can reach around the substrate.
The LLM runtime implements the same `turn(obs, act)`; these scripted characters are the
regression suite it gets measured against.

The base class is the honest default; scripted strategies override the hooks where they differ.
"""

from __future__ import annotations

import random

from sim.market import StubGrader, tagged
from society.observation import ActionsAPI, BidView, ContractView, JobView, Observation

_read = StubGrader()


def quality_of(artifact: str | None) -> float:
    """What a scripted reviewer sees when it inspects a delivery."""
    return _read.grade("", "", artifact or "").score


class Strategy:
    name = "base"
    gossips = True

    def __init__(self, work_cost: int | None = None, markup: float = 1.6, refuse_below: float = 0.35,
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

    def wake(self, obs: Observation) -> int:
        """How many members to pay to think this cycle: enough for the work in hand plus a
        little for new business, within what's free after commitments. Always one if there
        are promises to keep and a purse to keep them with."""
        per = int(obs.params.get("actions_per_member", 2))
        upkeep = int(obs.params.get("upkeep", 8_000))
        work = len(obs.to_deliver) + sum(1 for j in obs.my_jobs for p in j.parts
                                         if not p.done and p.capability in obs.capabilities)
        new_business = 2 if obs.board or obs.open_contracts else 0
        want = max(1, -(-(work + new_business) // per))
        afford = max(0, self.free(obs)) // upkeep
        return max(1 if obs.purse >= upkeep else 0, min(want, afford))

    # ── hooks ──────────────────────────────────────────────────
    def learn(self, obs: Observation) -> None:
        """Competition sets margins: drift up after a win, down after a loss, never below cost."""
        for e in obs.events:
            if e.kind == "awarded":
                self.markup = min(2.0, self.markup * 1.02)
            elif e.kind == "bid_lost":
                self.markup = max(1.1, self.markup * 0.98)

    def review(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        ok = quality_of(c.artifact) >= 0.5
        act.review(c.id, ok, "" if ok else "below the rubric")

    def deliver(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if obs.capacity and act.spend(self.cost(obs, c.capability), f"work {c.id}"):
            act.deliver(c.id, self.artifact(obs, c.capability), self.cites(obs, c.capability))

    def rate(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        """Truthfully: a prime that paid, or fairly rejected bad work, was a good counterparty."""
        fair = c.status == "accepted" or (c.status == "rejected" and quality_of(c.artifact) < 0.5) or c.status == "failed"
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
        if len(obs.my_jobs) >= self.max_jobs or obs.capacity < 2:
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

    # ── money ──────────────────────────────────────────────────
    def free(self, obs: Observation) -> int:
        """Purse minus everything already promised: remainders owed, work we've won,
        and the rest of the jobs we're prime on. Committing past this is how a
        community spirals into default."""
        sub_share = obs.params.get("sub_share", 0.4)
        promised = obs.owed + sum(self.cost(obs, c.capability) for c in obs.to_deliver)
        for job in obs.my_jobs:
            for p in job.parts:
                if p.done or p.pending in ("awarded", "delivered"):
                    continue
                promised += self.cost(obs, p.capability) if p.capability in obs.capabilities else round(job.reward * sub_share)
        return obs.purse - promised

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
