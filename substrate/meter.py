"""Compute metering: every model call is debited from the caller's purse at list price.

Two kinds of spend, kept apart (see substrate/ledger.py):

    notional  what the society charges itself, in the ledger's own currency. In a SIM world this
              is created money: flat upkeep, and model calls priced at list even when they ran
              on a free local model.
    real      what a real API bill costs you, always in USD. In a SIM world it is recorded
              separately (owner:capital -> ext:anthropic) so a simulation never hides a real bill.
              `real_ceiling` is the kill-switch that matters: it trips on real dollars per day.

Prices are USD per million tokens (Anthropic first-party list prices, cached 2026-06-24).
Cache writes assume the 5-minute TTL (1.25x input).
"""

from __future__ import annotations

from dataclasses import dataclass

from substrate.ledger import SIM, USD, InsufficientFunds, Ledger, purse
from substrate.telemetry import NULL, Hub


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25


PRICES: dict[str, Price] = {
    "claude-haiku-4-5": Price(1.00, 5.00, 0.10),
    "claude-sonnet-5": Price(2.00, 10.00, 0.20),
    "claude-opus-5": Price(5.00, 25.00, 0.50),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20),
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def cost_micros(model: str, usage: Usage) -> int:
    """Cost in micro-dollars. $1/Mtok == 1 micro-dollar per token."""
    p = PRICES[model]
    return round(
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_input_tokens * p.cache_read
        + usage.cache_creation_input_tokens * p.cache_write
    )


class KillSwitch(Exception):
    """The society's daily ceiling was hit. Everything halts until a human resets it."""


class BudgetExhausted(Exception):
    pass


class Meter:
    def __init__(self, ledger: Ledger, daily_ceiling: int, cycles_per_day: int = 1, hub: Hub = NULL,
                 real_ceiling: int = 5_000_000):
        self.hub = hub
        self.ledger = ledger
        self.daily_ceiling = daily_ceiling  # notional, in the ledger's currency
        self.real_ceiling = real_ceiling  # real USD micro-dollars per day ($5 by default)
        self.real_spent_today = 0
        self.sink = "compute" if ledger.currency == SIM else "ext:anthropic"
        self.cycles_per_day = cycles_per_day
        self.halted = False
        self._day = 0
        self._spent_today = 0
        self._task_spend: dict[str, int] = {}
        self._task_budget: dict[str, int] = {}
        self.by_community: dict[str, int] = {}

    def open_task(self, task_id: str, budget: int) -> None:
        self._task_budget[task_id] = budget
        self._task_spend.setdefault(task_id, 0)

    def remaining(self, task_id: str) -> int:
        return self._task_budget[task_id] - self._task_spend.get(task_id, 0)

    def charge(self, community: str, amount: int, *, cycle: int, task_id: str | None = None, memo: str = "") -> None:
        """Debit compute. Raises InsufficientFunds (silence), BudgetExhausted, or KillSwitch."""
        if self.halted:
            raise KillSwitch("society halted")
        day = cycle // self.cycles_per_day
        self._roll(day)
        if self._spent_today + amount > self.daily_ceiling:
            self.halted = True
            self.hub.emit("meter.kill_switch", cycle, reason="daily ceiling", spent=self._spent_today, ceiling=self.daily_ceiling)
            raise KillSwitch(f"daily ceiling {self.daily_ceiling} reached on day {day}")
        if task_id is not None and task_id in self._task_budget and self.remaining(task_id) < amount:
            raise BudgetExhausted(task_id)
        self.ledger.transfer(purse(community), self.sink, amount, cycle=cycle, kind="compute", memo=memo)
        self._spent_today += amount
        self.by_community[community] = self.by_community.get(community, 0) + amount
        if task_id is not None:
            self._task_spend[task_id] = self._task_spend.get(task_id, 0) + amount
        self.hub.emit("meter.charge", cycle, community=community, amount=amount, memo=memo, spent_today=self._spent_today)

    def _roll(self, day: int) -> None:
        if day != self._day:
            self._day, self._spent_today, self.real_spent_today = day, 0, 0

    def charge_usage(self, community: str, model: str, usage: Usage, *, cycle: int, real: bool, **kw) -> int:
        """Charge a model call to the community. `real` means someone is billed for it
        (Anthropic); a local model is not real. Real spend is recorded before any limit is
        checked, because the money has already gone."""
        amount = cost_micros(model, usage)
        if real:
            self._roll(cycle // self.cycles_per_day)
            if self.ledger.currency != USD:
                self.ledger.transfer("owner:capital", "ext:anthropic", amount, cycle=cycle, kind="api",
                                     memo=f"{community} {model}", currency=USD)
            self.real_spent_today += amount
            self.hub.emit("meter.real", cycle, community=community, model=model, amount=amount,
                          spent_today=self.real_spent_today, ceiling=self.real_ceiling)
        self.charge(community, amount, cycle=cycle, memo=model, **kw)
        if real and self.real_spent_today >= self.real_ceiling:
            self.halt(f"real spend ${self.real_spent_today / 1e6:.2f} reached the ${self.real_ceiling / 1e6:.2f} daily ceiling", cycle)
            raise KillSwitch("real-dollar ceiling reached")
        return amount

    def real_spent_total(self) -> int:
        return self.ledger.balance("ext:anthropic", USD)

    def can_afford(self, community: str, amount: int) -> bool:
        return self.ledger.balance(purse(community)) >= amount and not self.halted

    def halt(self, reason: str, cycle: int | None = None) -> None:
        self.halted = True
        self.hub.emit("meter.kill_switch", cycle, reason=reason, spent=self._spent_today, ceiling=self.daily_ceiling)

    def reset(self) -> None:
        """Clear the halt. Notional spend restarts; real spend doesn't, since it happened.
        Raise `real_ceiling` to go on after a real-dollar halt."""
        self.halted = False
        self._spent_today = 0


__all__ = ["PRICES", "Usage", "cost_micros", "Meter", "KillSwitch", "BudgetExhausted", "InsufficientFunds"]
