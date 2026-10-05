"""Sales channels: where a listed product is sold (your decision, 5 Oct: combinations, so one product can be on
several at once). Each channel is an adapter behind the same small port; the store's desk lists, reprices and
unlists through it, and collects each cycle's sales.

`FakeChannel` is for tests, the golden master and dry runs: a seeded demand model (better-graded, cheaper products
sell more often) with each channel's fee shape. The real channels (Etsy, Lemon Squeezy) join in P2.7, test mode
first, behind the gate: nothing reaches one without your approval.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

USD = 1_000_000  # µ$ per dollar


@dataclass(frozen=True)
class Sale:
    listing: str
    gross: int  # µ$ paid by the buyer
    fee: int  # µ$ the channel kept
    cycle: int
    refund: bool = False  # a refund of an earlier sale: the maker gives back what it was paid


class Channel(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def manual(self) -> bool: ...  # True: you list on it by hand from a kit, then link the listing (no listing API)

    def list(self, title: str, description: str, tags: tuple[str, ...], price: int, quality: float,
             files: dict | None = None) -> str:
        """List a product (with its files: pdf, cover); its listing id on this channel ("" for a manual channel)."""
        ...

    def set_price(self, listing: str, price: int) -> None: ...

    def unlist(self, listing: str) -> None: ...

    def sales(self, cycle: int) -> list[Sale]:
        """Sales since the last call."""
        ...


@dataclass
class FakeChannel:
    name: str
    manual: bool = False
    seed: int = 0
    fee_share: float = 0.065  # of the sale
    fee_fixed: int = 200_000  # µ$ a sale
    base_rate: float = 0.08  # chance a cycle that a $5 listing graded 1.0 sells
    listings: dict[str, tuple[int, float]] = field(default_factory=dict)  # id -> (price µ$, quality)
    seq: int = 0

    def list(self, title, description, tags, price, quality, files=None) -> str:
        if self.manual:
            return ""  # listed by hand, then linked (as Lemon Squeezy)
        self.seq += 1
        listing = f"{self.name}-{self.seq}"
        self.listings[listing] = (price, quality)
        return listing

    def link(self, listing: str) -> None:
        self.listings[listing] = (5 * USD, 0.9)

    def set_price(self, listing: str, price: int) -> None:
        if listing in self.listings:
            self.listings[listing] = (price, self.listings[listing][1])

    def unlist(self, listing: str) -> None:
        self.listings.pop(listing, None)

    def sales(self, cycle: int) -> list[Sale]:
        out = []
        for listing, (price, quality) in sorted(self.listings.items()):
            chance = min(0.9, self.base_rate * quality * (5 * USD / max(price, USD)) ** 0.5)
            if random.Random(f"{self.name}:{self.seed}:{cycle}:{listing}").random() < chance:
                out.append(Sale(listing, price, round(price * self.fee_share) + self.fee_fixed, cycle))
        return out


def fake_channels(seed: int) -> dict[str, FakeChannel]:
    """The two you chose, with their fee shapes (roughly: Etsy's listing, transaction and processing fees; Lemon
    Squeezy's 5% and 50¢)."""
    return {"etsy": FakeChannel("etsy", seed=seed, fee_share=0.095, fee_fixed=450_000),
            "lemonsqueezy": FakeChannel("lemonsqueezy", seed=seed, fee_share=0.05, fee_fixed=500_000, base_rate=0.05)}
