"""Phase 0's three characters. Keep these forever as a regression suite: any change to the
incentive rules gets re-run against them, so a tweak that makes defection pay shows up
immediately.
"""

from __future__ import annotations

from society.community import Community
from society.strategies.base import Job, Strategy, View, Work


class Cooperator(Strategy):
    """Bids at cost plus a margin, delivers real work, reports truthfully, publishes what works."""

    name = "cooperator"


class Defector(Strategy):
    """Underbids everything, pockets the advance, delivers junk."""

    name = "defector"

    def take_market_job(self, me, capabilities, reward, sub_share, view) -> bool:
        return False  # would have to deliver to the market, which can't be scammed

    def bid(self, me: Community, job: Job, view: View) -> int | None:
        if not me.can(job.capability):
            return None
        return max(1, round(job.reward * 0.35))  # zero cost: undercut anyone honest

    def work(self, me: Community, capability: str, view: View) -> Work:
        return Work(quality=view.rng.uniform(0.0, 0.2), cost=0)

    def publish(self, me, view) -> str | None:
        return None

    def gossips(self, me) -> bool:
        return False


class FreeRider(Strategy):
    """Takes the basic budget and contributes nothing: no market jobs, no bids, no playbooks."""

    name = "free-rider"

    def take_market_job(self, me, capabilities, reward, sub_share, view) -> bool:
        return False

    def bid(self, me, job, view) -> int | None:
        return None

    def publish(self, me, view) -> str | None:
        return None

    def gossips(self, me) -> bool:
        return False
