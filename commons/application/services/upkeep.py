"""Upkeep: what thinking costs. The basic budget tops up poor purses only (enough to think, not enough to coast), and
each co-op decides how many members to wake and pays for them; none awake means silence this cycle. The rules are the
treasury's (commons/domain/treasury.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.domain.treasury import floor_top_up, members_to_wake
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.society import World


class Upkeep:
    def __init__(self, world: World):
        self.w = world

    def floor(self) -> None:
        """The basic budget tops up poor purses only: enough to think, not enough to coast.
        A community that never wakes can't bank handouts, and a rich one doesn't need them."""
        p = self.w.params
        for c in self.w.living():
            top_up = floor_top_up(purse=self.w.ledger.balance(purse(c.name)), cap=p.money.floor_cap,
                                  treasury=self.w.ledger.balance("treasury"), budget=p.money.basic_budget)
            if top_up is None:
                return
            if top_up:
                self.w.ledger.transfer("treasury", purse(c.name), top_up, cycle=self.w.cycle, kind="floor")

    def wake(self) -> None:
        """Each community decides how many members to wake, and pays for them. Thinking is the
        cost of doing business, so it is a choice; none awake means silence this cycle."""
        p = self.w.params
        for c in list(self.w.communities.values()):
            c.capacity = 0
            if c.dissolved:
                c.thinking, c.active = 0, False
                continue
            want = c.strategy.wake(self.w.observe(c))
            c.thinking = members_to_wake(wanted=want, members=c.members, purse=self.w.ledger.balance(purse(c.name)),
                                         upkeep=p.money.upkeep)
            if c.thinking:
                try:
                    self.w.meter.charge(c.name, c.thinking * p.money.upkeep, cycle=self.w.cycle, memo="upkeep")
                except InsufficientFunds:
                    c.thinking = 0
            c.active = c.thinking > 0
            c.capacity = c.thinking * p.money.actions_per_member
