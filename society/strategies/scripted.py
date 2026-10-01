"""Phase 0's three characters, ported to turns. Keep these forever as a regression suite: any
change to the incentive rules gets re-run against them, so a tweak that makes defection pay
shows up immediately.
"""

from __future__ import annotations

from society.grading import tagged
from society.observation import ActionsAPI, ContractView, Observation
from society.strategies.base import Strategy


class Cooperator(Strategy):
    """Bids at cost plus a margin, delivers real work, reports truthfully, publishes what works."""

    name = "cooperator"


class Defector(Strategy):
    """Underbids everything, pockets the advance, delivers junk."""

    name = "defector"
    gossips = False

    def claim(self, obs, act) -> None:
        return  # would have to deliver to the market, which can't be scammed

    def bid(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if c.capability in obs.capabilities and c.my_bid is None and obs.capacity:
            act.bid(c.id, max(1, round(c.max_price * 0.35)))  # zero cost: undercut anyone honest

    def deliver(self, obs: Observation, act: ActionsAPI, c: ContractView) -> None:
        if obs.capacity:
            act.deliver(c.id, tagged(self.rng.uniform(0.0, 0.2), " junk"))

    def publish(self, obs, act) -> None:
        return

    def grow(self, obs, act) -> None:
        return

    def dispute(self, obs, act, c) -> None:
        return


class FreeRider(Strategy):
    """Takes the basic budget and contributes nothing: no market jobs, no bids, no playbooks."""

    name = "free-rider"
    gossips = False

    def wake(self, obs) -> int:
        return 1  # stays awake on the basic budget

    def turn(self, obs, act) -> None:
        return
