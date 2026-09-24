"""The decisions a community makes each cycle.

A strategy only decides. The engine signs, publishes, moves money and records outcomes,
so no strategy can reach around the substrate. The base class is the honest default;
scripted strategies override the hooks where they differ.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from society.community import Community


class View(Protocol):
    """What a community can see when it decides. Implemented by the sim engine."""

    rng: random.Random
    cycle: int

    def balance(self) -> int: ...
    def score(self, subject: str, capability: str) -> float: ...
    def standing(self, subject: str) -> float: ...
    def playbook_for(self, capability: str) -> str | None: ...
    def authored(self, capability: str) -> bool: ...


@dataclass(frozen=True)
class Job:
    job_id: str
    capability: str
    reward: int
    advance_frac: float = 0.0


@dataclass(frozen=True)
class Work:
    quality: float
    cost: int
    cites: tuple[str, ...] = ()


class Strategy:
    name = "base"

    def __init__(self, work_cost: int = 25_000, markup: float = 1.6, refuse_below: float = 0.35, explore: float = 0.1):
        self.work_cost = work_cost
        self.markup = markup
        self.refuse_below = refuse_below
        # Without exploration an unknown bidder never beats an incumbent with a track
        # record, and the market crystallizes around whoever got lucky first.
        self.explore = explore

    # ── market ─────────────────────────────────────────────────
    def take_market_job(self, me: Community, capabilities: tuple[str, ...], reward: int, sub_share: float, view: View) -> bool:
        """Take a job only if we can do part of it and finance all of it from the purse."""
        if not any(me.can(c) for c in capabilities):
            return False
        need = sum(self._cost(c, view) if me.can(c) else reward * sub_share for c in capabilities)
        return view.balance() >= 1.5 * need

    # ── contract-net ───────────────────────────────────────────
    def bid(self, me: Community, job: Job, view: View) -> int | None:
        if not me.can(job.capability):
            return None
        cost = self._cost(job.capability, view)
        price = round(cost * self.markup)
        if price > job.reward or view.balance() + price * job.advance_frac < cost:
            return None  # never promise work we can't fund
        return price

    def choose(self, me: Community, job: Job, bids: list[tuple[str, int]], view: View) -> str | None:
        """Refuse anyone we don't trust; usually take the best expected value, sometimes explore."""
        acceptable = [
            (b, p) for b, p in bids
            if view.score(b, job.capability) >= self.refuse_below and view.standing(b) >= self.refuse_below
        ]
        if not acceptable:
            return None
        if view.rng.random() < self.explore:
            return view.rng.choice(acceptable)[0]
        return max(acceptable, key=lambda bp: view.score(bp[0], job.capability) - 0.5 * bp[1] / job.reward)[0]

    def work(self, me: Community, capability: str, view: View) -> Work:
        playbook = view.playbook_for(capability)
        quality = view.rng.uniform(0.7, 1.0)
        if view.rng.random() < 0.05:  # honest mistakes happen
            quality = view.rng.uniform(0.2, 0.5)
        if playbook:
            quality = min(1.0, quality + 0.05)
        return Work(quality, self._cost(capability, view), (playbook,) if playbook else ())

    def on_bid_result(self, me: Community, won: bool) -> None:
        """Competition sets margins: drift up after a win, down after a loss, never below cost."""
        self.markup = min(2.0, self.markup * 1.02) if won else max(1.1, self.markup * 0.98)

    def accept(self, me: Community, quality: float) -> bool:
        return quality >= 0.5

    def attest(self, me: Community, outcome: float) -> float:
        return outcome

    # ── knowledge ──────────────────────────────────────────────
    def publish(self, me: Community, view: View) -> str | None:
        """Write up a method once we've done something enough times to know it works."""
        for cap in sorted(me.capabilities):
            if me.deliveries.get(cap, 0) >= 5 and not view.authored(cap):
                return cap
        return None

    # ── reputation ─────────────────────────────────────────────
    def gossips(self, me: Community) -> bool:
        return True

    def _cost(self, capability: str, view: View) -> int:
        return round(self.work_cost * (0.7 if view.playbook_for(capability) else 1.0))
