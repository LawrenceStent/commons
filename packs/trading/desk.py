"""The trading desk: the pack's broker as a kernel desk (commons/domain/desk.py).

Each cycle it opens by fetching quotes for the universe and marking every account to market (stops, the daily loss
pause, the kill criterion), and closes by settling performance every `horizon` cycles: each co-op's risk-adjusted
excess return over the window becomes credits from the treasury, which pay for its thinking (the capital economy).
Its state, accounts and windows and the fake market's path, is saved with the society.

Tools, for co-ops: buy (a stop is required), sell, raise_stop. Prices, the portfolio and how the window is going are
in each co-op's view, so reading them costs nothing but the tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from commons.substrate.ledger import purse
from packs.trading.broker import Account, Costs, Limits, Quote
from packs.trading.performance import benchmark, payout, score
from packs.trading.prices import NEW_YORK, UNIVERSE

S, N, I = {"type": "string"}, {"type": "number"}, {"type": "integer"}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "why": {"type": "string", "description": "optional: why"}},
            "required": required, "additionalProperties": False}


TOOLS = (
    {"name": "buy", "description": "Buy a symbol on paper at the market price, for an amount in dollars, with a stop: "
     "stop_pct is how far below the fill it sells by itself (0.01 to 0.15). At most 20% of your account in one symbol; "
     "you need the cash (no leverage). Refused while its market is closed. Fees and slippage apply.",
     "input_schema": _schema({"symbol": S, "amount": N, "stop_pct": N}, ["symbol", "amount", "stop_pct"])},
    {"name": "raise_stop", "description": "Move a position's stop up to stop_pct below the current price (0.01 to "
     "0.15). Stops can only be raised, never lowered.",
     "input_schema": _schema({"symbol": S, "stop_pct": N}, ["symbol", "stop_pct"])},
    {"name": "sell", "description": "Sell a position on paper at the market price: all of it, or qty units. No "
     "shorting: you can only sell what you hold. Refused while its market is closed.",
     "input_schema": _schema({"symbol": S, "qty": N}, ["symbol"])},
)


@dataclass
class Window:
    """One horizon's record for a co-op: its account value each cycle, and the prices the benchmark starts from."""
    start_cycle: int
    values: list[float]
    prices: dict[str, float]


@dataclass
class TradingDesk:
    market: Any  # FakeMarket or LiveMarket (packs/trading/prices.py)
    capital: float = 10_000.0  # paper dollars per co-op
    horizon: int = 24  # cycles per settlement
    per_return: int = 50_000_000  # µcr for a score of 1.0 (100 points of risk-adjusted excess return)
    costs: Costs = field(default_factory=Costs)
    limits: Limits = field(default_factory=Limits)
    universe: tuple[str, ...] = UNIVERSE
    tools: tuple = TOOLS
    accounts: dict[str, Account] = field(default_factory=dict)
    windows: dict[str, Window] = field(default_factory=dict)
    quotes: dict[str, Quote] = field(default_factory=dict)
    settlements: list[dict] = field(default_factory=list)  # every co-op's result at every horizon
    stops_fired: int = 0  # daily-loss pauses and kill criteria met, across the society

    # ── the cycle ──────────────────────────────────────────────
    def open(self, w) -> None:
        now = self.market.now(w.cycle)
        self.quotes.update(self.market.quotes(self.universe, now))
        day = datetime.fromtimestamp(now, NEW_YORK).date().isoformat()
        for c in w.living():
            account = self.accounts.setdefault(c.name, Account(self.capital, self.capital))
            before = (account.paused, account.stopped)
            for text in account.mark(self.quotes, day=day, costs=self.costs, limits=self.limits):
                w.tell(c.name, "desk", text)
            self.stops_fired += (account.paused, account.stopped) != before
            window = self.windows.setdefault(c.name, Window(w.cycle, [], self._prices()))
            window.values.append(account.value(self.quotes))

    def close(self, w) -> None:
        if w.cycle % self.horizon:
            return
        bench_now = self._prices()
        for name, window in list(self.windows.items()):
            if len(window.values) >= 2:
                self._settle(w, name, window, benchmark(window.prices, bench_now))
            self.windows[name] = Window(w.cycle, window.values[-1:], bench_now)

    def _settle(self, w, name: str, window: Window, bench: float) -> None:
        s = score(window.values, bench)
        pay = min(payout(s.value, self.per_return), w.ledger.balance("treasury"))
        if pay:
            w.ledger.transfer("treasury", purse(name), pay, cycle=w.cycle, kind="performance", memo=f"window {window.start_cycle}")
        record = {"coop": name, "cycle": w.cycle, "from": window.start_cycle, "ret": round(s.ret, 6),
                  "bench": round(s.bench, 6), "excess": round(s.excess, 6), "drawdown": round(s.drawdown, 6),
                  "sortino": None if s.sortino is None else round(s.sortino, 4), "score": round(s.value, 6),
                  "paid": pay, "fees": round(self.accounts[name].fees, 2)}
        self.settlements.append(record)
        w.hub.emit("desk.settle", w.cycle, **record)
        w.tell(name, "desk", f"window settled (cycles {window.start_cycle}-{w.cycle}): return {s.ret:+.2%}, benchmark "
                             f"{s.bench:+.2%}, drawdown {s.drawdown:.2%}, score {s.value:+.2%}; paid {pay} µcr")

    def _prices(self) -> dict[str, float]:
        return {s: q.price for s, q in self.quotes.items()}

    # ── tools ──────────────────────────────────────────────────
    def call(self, w, coop: str, tool: str, args: dict) -> tuple[bool, str]:
        account = self.accounts.get(coop)
        if account is None:
            return False, "you have no account yet; it opens at the start of the next cycle"
        symbol = str(args.get("symbol", "")).upper()
        quote = self.quotes.get(symbol)
        if quote is None:
            return False, f"no quote for {symbol!r}; the universe is {', '.join(self.universe)}"
        try:
            if tool == "buy":
                return account.buy(symbol, float(args["amount"]), stop_pct=float(args["stop_pct"]), quote=quote,
                                   costs=self.costs, limits=self.limits)
            if tool == "sell":
                qty = args.get("qty")
                return account.sell(symbol, None if qty in (None, "", "all") else float(qty), quote=quote, costs=self.costs)
            return account.set_stop(symbol, float(args["stop_pct"]), quote=quote, limits=self.limits)
        except (KeyError, TypeError, ValueError) as e:
            return False, f"bad arguments for {tool}: {e}"

    # ── what a co-op sees ──────────────────────────────────────
    def view(self, w, coop: str) -> str:
        a = self.accounts.get(coop)
        if a is None:
            return "Your paper account opens at the start of the next cycle."
        value = a.value(self.quotes)
        lines = [f"Paper account: value {value:,.2f} of {a.capital:,.0f} allocated · cash {a.cash:,.2f} · "
                 f"fees so far {a.fees:,.2f}" + (" · TRADING STOPPED (kill criterion)" if a.stopped else "")
                 + (" · paused today (daily loss limit)" if a.paused == a.day and not a.stopped else "")]
        for s, p in sorted(a.positions.items()):
            last = self.quotes[s].price if s in self.quotes else p.last
            lines.append(f"  {s}: {p.qty:.6g} at {p.entry:,.2f}, now {last:,.2f} ({last / p.entry - 1:+.2%}), stop {p.stop:,.2f}")
        if window := self.windows.get(coop):
            bench = benchmark(window.prices, self._prices())
            ret = value / window.values[0] - 1 if window.values else 0.0
            due = self.horizon - (w.cycle - window.start_cycle)
            lines.append(f"This window (since cycle {window.start_cycle}, settles in {due} cycles): return {ret:+.2%}, "
                         f"benchmark {bench:+.2%}")
        lines.append("Quotes: " + " · ".join(f"{s} {q.price:,.2f}{'' if q.fresh else ' (closed)'}"
                                              for s, q in sorted(self.quotes.items())))
        lines.append(f"Rules: a stop with every buy ({self.limits.stop_min:.0%}-{self.limits.stop_max:.0%} below); at most "
                     f"{self.limits.position_cap:.0%} in one symbol; no leverage or shorting; down "
                     f"{self.limits.daily_loss:.0%} in a day pauses trading; down {self.limits.kill_loss:.0%} of capital "
                     "stops it for good. Paid each window for return above the benchmark, less half the drawdown.")
        return "\n".join(lines)
