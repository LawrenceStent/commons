"""Scripted desks, for tests and the golden master. They read the desk's state directly (a model-backed co-op reads its
view) and act through the same tools, under the same limits.

    Holder     buys a spread on its first turn, with wide stops, and keeps it
    Momentum   each turn, buys what rose since its last look and sells what fell
    Sitter     keeps its cash
    Reckless   tries every forbidden order (no stop, a giant position, a short), then trades like Momentum
"""

from __future__ import annotations

import random

BASKET = ("BTC-USD", "ETH-USD", "SPY", "QQQ", "MSFT")


class Desk:
    name = "desk"
    gossips = False

    def __init__(self):
        self.rng = random.Random(0)  # the world reseeds this per community
        self.seen: dict[str, float] = {}

    def wake(self, obs) -> int:
        return 1

    def turn(self, obs, act) -> None:
        self.trade(act, act.w.desk)
        self.seen = {s: q.price for s, q in act.w.desk.quotes.items()}

    def trade(self, act, desk) -> None:
        pass

    @staticmethod
    def worth(act, desk) -> float:
        return desk.accounts[act.me.name].value(desk.quotes)


class Holder(Desk):
    name = "holder"

    def trade(self, act, desk):
        account = desk.accounts.get(act.me.name)
        if account is None or account.positions or account.trades:
            return
        for s in BASKET:
            if s in desk.quotes and desk.quotes[s].fresh:
                act.desk_call("buy", {"symbol": s, "amount": round(0.18 * self.worth(act, desk), 2), "stop_pct": 0.15})


class Momentum(Desk):
    name = "momentum"

    def trade(self, act, desk):
        account = desk.accounts.get(act.me.name)
        if account is None:
            return
        for s, q in sorted(desk.quotes.items()):
            before = self.seen.get(s)
            if before is None or not q.fresh:
                continue
            if q.price > before and s not in account.positions:
                act.desk_call("buy", {"symbol": s, "amount": round(0.1 * self.worth(act, desk), 2), "stop_pct": 0.05})
            elif q.price < before and s in account.positions:
                act.desk_call("sell", {"symbol": s})


class Sitter(Desk):
    name = "sitter"


class Reckless(Momentum):
    name = "reckless"

    def trade(self, act, desk):
        if desk.accounts.get(act.me.name) is None:
            return
        act.desk_call("buy", {"symbol": "BTC-USD", "amount": 500, "stop_pct": 0})  # no stop
        act.desk_call("buy", {"symbol": "BTC-USD", "amount": 0.9 * self.worth(act, desk), "stop_pct": 0.1})  # giant
        act.desk_call("sell", {"symbol": "NVDA", "qty": 10})  # a short
        act.desk_call("buy", {"symbol": "BTC-USD", "amount": 1e9, "stop_pct": 0.1})  # leverage
        super().trade(act, desk)
