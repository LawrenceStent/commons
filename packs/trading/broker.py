"""The paper broker: a co-op's account, its orders and the limits on them. Pure rules, no prices fetched and no world.

The limits are code from day one, never prompts (FRAMEWORK.md §7.2):
    a stop with every buy      between `stop_min` and `stop_max` below the fill; stops may only be raised
    a cap on each position     at most `position_cap` of the account's value, adds included
    no leverage, no shorting   a buy needs the cash; a sale needs the holding
    a daily loss pause         down `daily_loss` on the day: everything is sold and trading pauses until the next day
    a kill criterion           down `kill_loss` of the capital allocated: everything is sold and trading stops for good

Orders are market orders, filled at the quote with slippage against you and a fee on the notional. A quote that isn't
fresh (its market is shut) can't be traded on, and doesn't trigger stops. Money is paper dollars, kept apart from the
society's credits: performance becomes credits only when it is settled (packs/trading/performance.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    at: float  # when it was quoted (seconds since the epoch)
    fresh: bool = True  # tradeable now: its market is open and the quote is recent


@dataclass(frozen=True)
class Costs:
    fee: float = 0.001  # of the notional, each way
    slippage: float = 0.0005  # of the price, against you


@dataclass(frozen=True)
class Limits:
    stop_min: float = 0.01
    stop_max: float = 0.15
    position_cap: float = 0.20
    daily_loss: float = 0.03
    kill_loss: float = 0.20


@dataclass
class Position:
    symbol: str
    qty: float
    entry: float  # average fill price
    stop: float
    last: float  # the last price seen, for valuing it when no quote comes


@dataclass
class Account:
    capital: float  # paper dollars allocated
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    fees: float = 0.0
    trades: int = 0
    day: str | None = None
    day_start: float = 0.0  # the account's value when the day began
    paused: str | None = None  # the day trading is paused for (a daily loss)
    stopped: bool = False  # the kill criterion was met
    pauses: int = 0  # daily-loss pauses so far

    def __setstate__(self, state: dict) -> None:  # accounts saved before `pauses` existed (4 Oct) load with none
        self.__dict__.update({"pauses": 0, **state})

    def value(self, quotes: dict[str, Quote]) -> float:
        return self.cash + sum(p.qty * (quotes[s].price if s in quotes else p.last) for s, p in self.positions.items())

    # ── orders ─────────────────────────────────────────────────
    def buy(self, symbol: str, notional: float, *, stop_pct: float | None, quote: Quote, costs: Costs,
            limits: Limits) -> tuple[bool, str]:
        if why := self._closed(quote):
            return False, why
        if not stop_pct or stop_pct <= 0:
            return False, "every buy needs a stop: give stop_pct, how far below the fill to sell (0.01 to 0.15)"
        if not limits.stop_min <= stop_pct <= limits.stop_max:
            return False, f"the stop must be between {limits.stop_min:.0%} and {limits.stop_max:.0%} below the fill"
        if notional <= 0:
            return False, "the amount must be positive"
        if notional > self.cash:
            return False, f"not enough cash: {self.cash:.2f} available (no leverage)"
        held = self.positions.get(symbol)
        worth = (held.qty * quote.price if held else 0.0) + notional
        room = limits.position_cap * self.value({symbol: quote}) - (worth - notional)
        if notional > room:
            return False, (f"that would put more than {limits.position_cap:.0%} of the account in {symbol}: "
                           f"at most {max(0.0, room):,.2f} more")
        fill = quote.price * (1 + costs.slippage)
        fee = notional * costs.fee
        qty = (notional - fee) / fill
        stop = fill * (1 - stop_pct)
        if held:
            entry = (held.entry * held.qty + fill * qty) / (held.qty + qty)
            self.positions[symbol] = Position(symbol, held.qty + qty, entry, max(held.stop, stop), quote.price)
        else:
            self.positions[symbol] = Position(symbol, qty, fill, stop, quote.price)
        self.cash -= notional
        self.fees += fee
        self.trades += 1
        return True, f"bought {qty:.6g} {symbol} at {fill:.2f} (fee {fee:.2f}); stop {stop:.2f}"

    def sell(self, symbol: str, qty: float | None, *, quote: Quote, costs: Costs, why: str = "") -> tuple[bool, str]:
        """Sell `qty`, or all of it (None)."""
        held = self.positions.get(symbol)
        if held is None:
            return False, f"you hold no {symbol} (no shorting)"
        if not why and (closed := self._market_shut(quote)):
            return False, closed
        qty = held.qty if qty is None else qty
        if qty <= 0:
            return False, "the quantity must be positive"
        if qty > held.qty * (1 + 1e-9):
            return False, f"you can't sell more than you hold ({held.qty:.6g} {symbol}; no shorting)"
        qty = min(qty, held.qty)
        fill = quote.price * (1 - costs.slippage)
        fee = qty * fill * costs.fee
        self.cash += qty * fill - fee
        self.fees += fee
        self.trades += 1
        if held.qty - qty <= held.qty * 1e-9:
            del self.positions[symbol]
        else:
            self.positions[symbol] = Position(symbol, held.qty - qty, held.entry, held.stop, quote.price)
        return True, f"sold {qty:.6g} {symbol} at {fill:.2f} (fee {fee:.2f}){f': {why}' if why else ''}"

    def set_stop(self, symbol: str, stop_pct: float, *, quote: Quote, limits: Limits) -> tuple[bool, str]:
        held = self.positions.get(symbol)
        if held is None:
            return False, f"you hold no {symbol}"
        if not limits.stop_min <= stop_pct <= limits.stop_max:
            return False, f"the stop must be between {limits.stop_min:.0%} and {limits.stop_max:.0%} below the price"
        stop = quote.price * (1 - stop_pct)
        if stop < held.stop:
            return False, f"a stop can only be raised: {symbol}'s is {held.stop:.2f}, this would be {stop:.2f}"
        self.positions[symbol] = Position(symbol, held.qty, held.entry, stop, quote.price)
        return True, f"{symbol} stop raised to {stop:.2f}"

    # ── each cycle ─────────────────────────────────────────────
    def mark(self, quotes: dict[str, Quote], *, day: str, costs: Costs, limits: Limits) -> list[str]:
        """New prices: stops hit on fresh quotes, then the day's loss and the kill criterion. What to tell the co-op."""
        told: list[str] = []
        if day != self.day:
            self.day, self.day_start = day, self.value(quotes)
        for s, p in list(self.positions.items()):
            if s in quotes:
                p.last = quotes[s].price
                if quotes[s].fresh and quotes[s].price <= p.stop:
                    told.append(self.sell(s, None, quote=quotes[s], costs=costs, why=f"stop hit at {p.stop:.2f}")[1])
        now = self.value(quotes)
        if not self.stopped and now < self.capital * (1 - limits.kill_loss):
            told += self._close_all(quotes, costs, f"kill criterion: down {1 - now / self.capital:.0%} of capital")
            self.stopped = True
            told.append("trading has stopped for good: the account is down more than the kill criterion allows")
        elif self.paused != day and self.day_start and now < self.day_start * (1 - limits.daily_loss):
            told += self._close_all(quotes, costs, f"daily loss limit: down {1 - now / self.day_start:.1%} today")
            self.paused = day
            self.pauses += 1
            told.append("daily loss limit reached: everything sold, trading paused until the next day")
        return told

    def _close_all(self, quotes: dict[str, Quote], costs: Costs, why: str) -> list[str]:
        """Sell everything, at the last price seen where there's no quote (a limit can't wait for the market)."""
        return [self.sell(s, None, quote=quotes.get(s) or Quote(s, p.last, 0.0, fresh=False), costs=costs, why=why)[1]
                for s, p in list(self.positions.items())]

    def _closed(self, quote: Quote) -> str | None:
        if self.stopped:
            return "trading has stopped for good on this account (the kill criterion)"
        if self.paused == self.day and self.day is not None:
            return "trading is paused until the next day (the daily loss limit)"
        return self._market_shut(quote)

    @staticmethod
    def _market_shut(quote: Quote) -> str | None:
        return None if quote.fresh else f"{quote.symbol}'s market is closed (its last quote isn't fresh); try later"
