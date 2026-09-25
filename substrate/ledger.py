"""Double-entry ledger on SQLite. Amounts are integer micro-units of a currency.

Two currencies, never exchanged:

    SIM   created money. It exists only in simulations: seeded from `genesis`, paid out by the
          mock `market`, burned by notional `compute`. The dashboard shows it as "cr", never "$".
    USD   real money. Every unit traces to something that happened outside: capital the owner put
          in (`owner:capital`), a customer payment (`ext:stripe`), a real API bill (`ext:anthropic`),
          or a fee (`ext:fees`).

Every entry is in one currency and balances within it, so there is no path from SIM to USD.
Each currency has its own external accounts, which may go negative (they are the outside world);
a SIM entry can't touch a USD external account or the other way round.

Internal accounts, one set per currency:
    purse:<community>   a community's spendable balance (never negative)
    treasury            the shared treasury (never negative)

A ledger has a default currency, the one its society runs on: SIM for simulations, USD for a
live society. Calls that don't name a currency use it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from substrate.telemetry import NULL, Hub

SIM, USD = "SIM", "USD"
EXTERNAL: dict[str, frozenset[str]] = {
    SIM: frozenset({"genesis", "market", "compute"}),
    USD: frozenset({"owner:capital", "ext:stripe", "ext:anthropic", "ext:fees"}),
}
ALL_EXTERNAL = frozenset().union(*EXTERNAL.values())

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    cycle INTEGER NOT NULL,
    currency TEXT NOT NULL,
    kind TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS postings (
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    account TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS postings_account ON postings(account, currency);
CREATE TABLE IF NOT EXISTS balances (
    account TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount INTEGER NOT NULL,
    PRIMARY KEY (account, currency)
);
"""


class WrongCurrency(ValueError):
    """An entry touched another currency's external account: the SIM/USD wall."""


class InsufficientFunds(Exception):
    pass


def purse(community: str) -> str:
    return f"purse:{community}"


class Ledger:
    def __init__(self, path: str = ":memory:", hub: Hub = NULL, currency: str = SIM):
        if currency not in EXTERNAL:
            raise ValueError(f"unknown currency {currency}")
        self.hub = hub
        self.currency = currency
        # the console builds a world on one thread and drives it from the event loop's
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._balances: dict[tuple[str, str], int] = {
            (a, c): n for a, c, n in self.db.execute("SELECT account, currency, amount FROM balances")
        }

    def balance(self, account: str, currency: str | None = None) -> int:
        return self._balances.get((account, currency or self.currency), 0)

    def post(self, legs: Iterable[tuple[str, int]], *, cycle: int, kind: str, memo: str = "",
             currency: str | None = None) -> int:
        """Atomically apply legs that sum to zero in one currency. Internal accounts may not go negative."""
        cur = currency or self.currency
        if cur not in EXTERNAL:
            raise ValueError(f"unknown currency {cur}")
        legs = [(a, n) for a, n in legs if n]
        if sum(n for _, n in legs) != 0:
            raise ValueError(f"unbalanced entry: {legs}")
        foreign = [a for a, _ in legs if a in ALL_EXTERNAL and a not in EXTERNAL[cur]]
        if foreign:
            raise WrongCurrency(f"{cur} entry can't touch {', '.join(foreign)}")
        after: dict[str, int] = {}
        for account, n in legs:
            after[account] = after.get(account, self.balance(account, cur)) + n
        for account, amount in after.items():
            if amount < 0 and account not in EXTERNAL[cur]:
                raise InsufficientFunds(f"{account} would be {amount} {cur}")
        self.db.execute("BEGIN")
        try:
            entry = self.db.execute(
                "INSERT INTO entries (cycle, currency, kind, memo) VALUES (?, ?, ?, ?)", (cycle, cur, kind, memo)
            ).lastrowid
            self.db.executemany(
                "INSERT INTO postings (entry_id, account, currency, amount) VALUES (?, ?, ?, ?)",
                [(entry, a, cur, n) for a, n in legs],
            )
            self.db.executemany(
                "INSERT INTO balances (account, currency, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(account, currency) DO UPDATE SET amount = excluded.amount",
                [(a, cur, n) for a, n in after.items()],
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self._balances.update({(a, cur): n for a, n in after.items()})
        self.hub.emit("ledger.post", cycle, entry=entry, currency=cur, kind=kind, memo=memo, legs=legs)
        return entry

    def transfer(self, src: str, dst: str, amount: int, *, cycle: int, kind: str, memo: str = "",
                 currency: str | None = None) -> int:
        return self.post([(src, -amount), (dst, amount)], cycle=cycle, kind=kind, memo=memo, currency=currency)

    def settle_revenue(
        self,
        earner: str,
        amount: int,
        *,
        cycle: int,
        royalties: dict[str, int] | None = None,
        memo: str = "",
        source: str | None = None,
        tax: bool = True,
    ) -> dict[str, int]:
        """Revenue: 70% to the earner, 20% to the treasury, 10% to cited authors. With
        `tax=False` the treasury's 20% goes to the earner instead (90/0/10).

        `source` is where the money comes from: the mock `market` in a SIM ledger, a real
        payment processor such as `ext:stripe` in a USD one. `royalties` maps author
        community -> citation weight. With no citations the royalty slice goes to the treasury.
        """
        source = source or ("market" if self.currency == SIM else None)
        if source is None:
            raise WrongCurrency("real revenue needs a real source, e.g. source='ext:stripe'")
        to_earner = amount * (70 if tax else 90) // 100
        pool = amount * 10 // 100
        to_treasury = amount - to_earner - pool
        legs = [(source, -amount), (purse(earner), to_earner)]
        split: dict[str, int] = {}
        weight = sum((royalties or {}).values())
        if weight:
            for author, w in sorted(royalties.items()):
                split[author] = pool * w // weight
            to_treasury += pool - sum(split.values())
            legs += [(purse(a), n) for a, n in split.items()]
        else:
            to_treasury += pool
        legs.append(("treasury", to_treasury))
        self.post(legs, cycle=cycle, kind="revenue", memo=memo)
        return split

    def add_capital(self, amount: int, *, cycle: int, to: str = "treasury", memo: str = "") -> int:
        """Real money the owner puts in. The only way USD enters besides a customer paying."""
        return self.transfer("owner:capital", to, amount, cycle=cycle, kind="capital", memo=memo, currency=USD)

    def real(self) -> dict[str, int]:
        """The real-money position, positive numbers: what went in, came in, and went out."""
        b = lambda a: self.balance(a, USD)
        return {"capital_in": -b("owner:capital"), "revenue": -b("ext:stripe"),
                "api_spend": b("ext:anthropic"), "fees": b("ext:fees")}

    def total(self, currency: str | None = None) -> int:
        cur = currency or self.currency
        return sum(n for (_, c), n in self._balances.items() if c == cur)

    def check(self) -> None:
        """Every entry balances within its currency and cached balances match postings."""
        bad = self.db.execute(
            "SELECT entry_id FROM postings GROUP BY entry_id HAVING SUM(amount) != 0 OR COUNT(DISTINCT currency) > 1"
        ).fetchall()
        assert not bad, f"unbalanced or mixed-currency entries: {bad}"
        derived = {(a, c): n for a, c, n in self.db.execute(
            "SELECT account, currency, SUM(amount) FROM postings GROUP BY account, currency")}
        for key, amount in self._balances.items():
            assert derived.get(key, 0) == amount, key
        for cur in EXTERNAL:
            assert self.total(cur) == 0, f"{cur} does not net to zero"
