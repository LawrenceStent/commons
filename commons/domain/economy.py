"""Economies: how passing work is paid. A society's economy is chosen once, from its settings (`policy_for`); nothing
else in the code asks which economy it is. Adding one (trading's capital economy, say) means adding a class here.

    MarketPayment  an outside payer (the mock market) pays each passing job its value at once
    GrantPayment   a funder puts a budget into a pool each cycle (at most `cap_cycles` budgets banked); at the end of
                   the cycle, passing work shares the pool by value, never more than its value
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from commons.domain.ids import JobId
from commons.domain.money import Micros


class PaymentPolicy(Protocol):
    """Read only: an economy is chosen once and never changes."""

    @property
    def name(self) -> str: ...
    @property
    def pays_at_once(self) -> bool: ...  # False: passing work waits for `shares` at the end of the cycle
    @property
    def pool(self) -> str | None: ...  # the ledger account it pays from and funds, if it keeps one
    @property
    def funder(self) -> str | None: ...  # the outside account that funds the pool
    @property
    def source(self) -> str | None: ...  # where revenue comes from in the ledger (None: the default outside payer)
    @property
    def payer(self) -> str: ...  # how it's named when a co-op is told it was paid
    @property
    def queued(self) -> str: ...  # what a co-op is told when its passing work waits

    def funding(self, pool_balance: Micros) -> Micros: ...

    def shares(self, values: dict[JobId, Micros], pool: Micros) -> dict[JobId, Micros]: ...

    def view(self, pool_balance: Micros) -> tuple[Micros, Micros] | None: ...


@dataclass(frozen=True)
class MarketPayment:
    name: str = "market"
    pays_at_once: bool = True
    pool: str | None = None
    funder: str | None = None
    source: str | None = None
    payer: str = "the market"
    queued: str = ""

    def funding(self, pool_balance: Micros) -> Micros:
        return Micros(0)

    def shares(self, values: dict[JobId, Micros], pool: Micros) -> dict[JobId, Micros]:
        return dict(values)

    def view(self, pool_balance: Micros) -> None:
        return None


@dataclass(frozen=True)
class GrantPayment:
    budget: Micros
    cap_cycles: int
    name: str = "grant"
    pays_at_once: bool = False
    pool: str | None = "grants"
    funder: str | None = "funder"
    source: str | None = "grants"
    payer: str = "the grants"
    queued: str = "it shares this cycle's grants at the end of the cycle"

    def funding(self, pool_balance: Micros) -> Micros:
        """A top-up of one budget, never beyond `cap_cycles` budgets in the pool."""
        if self.budget <= 0:
            return Micros(0)
        return Micros(max(0, min(self.budget, self.budget * self.cap_cycles - pool_balance)))

    def shares(self, values: dict[JobId, Micros], pool: Micros) -> dict[JobId, Micros]:
        """By value, never more than the value; in proportion when the pool can't cover them all."""
        total = sum(values.values())
        return {jid: v if total <= pool else Micros(v * pool // total) for jid, v in values.items()}

    def view(self, pool_balance: Micros) -> tuple[Micros, Micros]:
        """(the pool now, the budget a cycle): what stewards are told."""
        return pool_balance, self.budget


def policy_for(economy: str, grant_budget: Micros, grant_cap_cycles: int) -> PaymentPolicy:
    if economy == "market":
        return MarketPayment()
    if economy == "grant":
        return GrantPayment(grant_budget, grant_cap_cycles)
    raise ValueError(f"no economy called {economy!r}; there is market and grant")
