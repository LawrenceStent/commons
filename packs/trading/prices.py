"""Prices for the trading pack: a fake market for tests and the golden master, and live quotes for forward runs.

Both answer `quotes(symbols, now)` with `Quote`s (packs/trading/broker.py) and `now(cycle)`, the time a cycle happens
at: the clock for live runs, `start + cycle × step_seconds` for the fake one. A quote is `fresh` when its market is
open; crypto never shuts, the US market is open 9:30 to 16:00 New York time on weekdays (holidays aren't modelled: a
holiday quote is simply stale, as its date gives away).

Live quotes come from two free APIs with no key, through the kernel's safe fetcher, whose egress allowlist holds just
their two hosts: Coinbase's spot price for crypto, and Yahoo's chart API for US ETFs and stocks (only its current
price and the time of it are read). Stooq, the first choice, put its quotes behind a browser check (3 Oct). Yahoo's
endpoint is unofficial: a keyed provider can replace it behind the same adapter. A symbol whose quote can't be had is
left out: the broker values a position at the last price it saw, and nothing trades on it.

There is no history tool and there are no backtests: the forward test only ever sees prices after it began.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from commons.adapters.web import Egress, Fetcher
from commons.application.ports import WebError
from packs.trading.broker import Quote

CRYPTO = ("BTC-USD", "ETH-USD", "SOL-USD")
US = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")
UNIVERSE = CRYPTO + US
HOSTS = ("api.coinbase.com", "query1.finance.yahoo.com")

NEW_YORK = ZoneInfo("America/New_York")
STALE_AFTER = 3600  # seconds: a quote older than this, in session, isn't fresh


def is_crypto(symbol: str) -> bool:
    return symbol.endswith("-USD")


def us_open(t: float) -> bool:
    ny = datetime.fromtimestamp(t, NEW_YORK)
    minutes = ny.hour * 60 + ny.minute
    return ny.weekday() < 5 and 9 * 60 + 30 <= minutes < 16 * 60


# ── the fake market ────────────────────────────────────────────
START_PRICES = {"BTC-USD": 60_000.0, "ETH-USD": 3_000.0, "SOL-USD": 150.0, "SPY": 570.0, "QQQ": 490.0,
                "AAPL": 230.0, "MSFT": 430.0, "NVDA": 120.0}
HOURLY_VOL = {"crypto": 0.008, "us": 0.003}


@dataclass
class FakeMarket:
    """A random walk per symbol, seeded: the same seed gives the same prices, cycle for cycle. US symbols only move
    while their market is open. Its state is saved with the society, so a resumed run carries on the same path."""
    seed: int = 0
    start: float = datetime(2026, 10, 5, 9, 0, tzinfo=NEW_YORK).timestamp()  # a Monday, before the US open
    step_seconds: float = 3600.0
    drift: float = 0.0  # per step, for tests that need a market going one way
    prices: dict[str, float] = field(default_factory=dict)
    at: float | None = None
    rng: random.Random | None = None

    def now(self, cycle: int) -> float:
        return self.start + cycle * self.step_seconds

    def quotes(self, symbols, now: float) -> dict[str, Quote]:
        if self.rng is None:
            self.rng = random.Random(f"fake-market:{self.seed}")
            self.prices = dict(START_PRICES)
        if now != self.at:
            self.at = now
            for s in sorted(self.prices):  # every symbol, in a fixed order, so the path doesn't depend on who asks
                shock = self.rng.gauss(self.drift, HOURLY_VOL["crypto" if is_crypto(s) else "us"])
                if is_crypto(s) or us_open(now):
                    self.prices[s] *= math.exp(shock)
        return {s: Quote(s, round(self.prices[s], 4), now, is_crypto(s) or us_open(now)) for s in symbols
                if s in self.prices}


# ── live quotes ────────────────────────────────────────────────
class LiveMarket:
    """Coinbase spot and Yahoo's chart API, read through the safe fetcher. The fetcher belongs to the process: a saved society
    leaves it out and builds a new one when it next needs a quote."""

    def __init__(self, fetcher: Fetcher | None = None):
        self._fetcher = fetcher

    @property
    def fetcher(self) -> Fetcher:
        if self._fetcher is None:
            self._fetcher = Fetcher(Egress(HOSTS))
        return self._fetcher

    def __getstate__(self) -> dict:
        return {"_fetcher": None}

    def now(self, cycle: int) -> float:
        return time.time()

    def quotes(self, symbols, now: float) -> dict[str, Quote]:
        out = {s: q for s in symbols if is_crypto(s) and (q := self._coinbase(s, now))}
        return out | {s: q for s in symbols if not is_crypto(s) and (q := self._yahoo(s, now))}

    def _coinbase(self, symbol: str, now: float) -> Quote | None:
        try:
            data = self.fetcher.json(f"https://api.coinbase.com/v2/prices/{symbol}/spot")
            return Quote(symbol, float(data["data"]["amount"]), now, fresh=True)
        except (WebError, KeyError, TypeError, ValueError):
            return None

    def _yahoo(self, symbol: str, now: float) -> Quote | None:
        try:
            meta = self.fetcher.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d")
            meta = meta["chart"]["result"][0]["meta"]
            price, quoted = float(meta["regularMarketPrice"]), float(meta["regularMarketTime"])
        except (WebError, KeyError, IndexError, TypeError, ValueError):
            return None
        return Quote(symbol, price, quoted, fresh=us_open(now) and now - quoted <= STALE_AFTER)
