"""Double-entry ledger on SQLite. Amounts are integer micro-dollars.

Account naming:
    purse:<community>   a community's spendable balance (never negative)
    treasury            the shared treasury (never negative)
    market              external revenue source (may go negative)
    compute             sink for model spend (may go negative)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

EXTERNAL = ("market", "compute", "genesis")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    cycle INTEGER NOT NULL,
    kind TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS postings (
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    account TEXT NOT NULL,
    amount INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS postings_account ON postings(account);
CREATE TABLE IF NOT EXISTS balances (
    account TEXT PRIMARY KEY,
    amount INTEGER NOT NULL
);
"""


class InsufficientFunds(Exception):
    pass


def purse(community: str) -> str:
    return f"purse:{community}"


class Ledger:
    def __init__(self, path: str = ":memory:"):
        # the console builds a world on one thread and drives it from the event loop's
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._balances: dict[str, int] = dict(self.db.execute("SELECT account, amount FROM balances"))

    def balance(self, account: str) -> int:
        return self._balances.get(account, 0)

    def post(self, legs: Iterable[tuple[str, int]], *, cycle: int, kind: str, memo: str = "") -> int:
        """Atomically apply legs that sum to zero. Internal accounts may not go negative."""
        legs = [(a, n) for a, n in legs if n]
        if sum(n for _, n in legs) != 0:
            raise ValueError(f"unbalanced entry: {legs}")
        after: dict[str, int] = {}
        for account, n in legs:
            after[account] = after.get(account, self.balance(account)) + n
        for account, amount in after.items():
            if amount < 0 and account not in EXTERNAL:
                raise InsufficientFunds(f"{account} would be {amount}")
        self.db.execute("BEGIN")
        try:
            entry = self.db.execute(
                "INSERT INTO entries (cycle, kind, memo) VALUES (?, ?, ?)", (cycle, kind, memo)
            ).lastrowid
            self.db.executemany(
                "INSERT INTO postings (entry_id, account, amount) VALUES (?, ?, ?)",
                [(entry, a, n) for a, n in legs],
            )
            self.db.executemany(
                "INSERT INTO balances (account, amount) VALUES (?, ?) "
                "ON CONFLICT(account) DO UPDATE SET amount = excluded.amount",
                list(after.items()),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self._balances.update(after)
        return entry

    def transfer(self, src: str, dst: str, amount: int, *, cycle: int, kind: str, memo: str = "") -> int:
        return self.post([(src, -amount), (dst, amount)], cycle=cycle, kind=kind, memo=memo)

    def settle_revenue(
        self,
        earner: str,
        amount: int,
        *,
        cycle: int,
        royalties: dict[str, int] | None = None,
        memo: str = "",
    ) -> dict[str, int]:
        """Market revenue: 70% to the earner, 20% to the treasury, 10% to cited authors.

        `royalties` maps author community -> citation weight. With no citations the
        royalty slice goes to the treasury.
        """
        to_earner = amount * 70 // 100
        pool = amount * 10 // 100
        to_treasury = amount - to_earner - pool
        legs = [("market", -amount), (purse(earner), to_earner)]
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

    def total(self) -> int:
        return sum(self._balances.values())

    def check(self) -> None:
        """Every entry balances and cached balances match postings."""
        bad = self.db.execute(
            "SELECT entry_id FROM postings GROUP BY entry_id HAVING SUM(amount) != 0"
        ).fetchall()
        assert not bad, f"unbalanced entries: {bad}"
        derived = dict(self.db.execute("SELECT account, SUM(amount) FROM postings GROUP BY account"))
        for account, amount in self._balances.items():
            assert derived.get(account, 0) == amount, account
