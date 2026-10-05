"""The treasury's rules, as pure functions: how revenue is split, who gets the floor, how many members a purse can
wake, and what a claim bond costs. The ledger and the world apply them; they decide nothing themselves."""

from __future__ import annotations

from typing import NamedTuple

from commons.domain.money import Micros

EARNER, EARNER_UNTAXED, ROYALTIES = 70, 90, 10  # percent of revenue


class RevenueSplit(NamedTuple):
    earner: Micros
    treasury: Micros
    royalties: dict[str, Micros]  # author co-op -> amount, in name order


def revenue_split(amount: Micros, royalties: dict[str, int] | None, *, tax: bool) -> RevenueSplit:
    """70% to the earner, 20% to the treasury, 10% to cited authors by citation weight. With `tax=False` (the treasury
    is at its reserve) the treasury's 20% goes to the earner. With no citations the royalty slice goes to the
    treasury, and so does what integer division leaves over."""
    to_earner = amount * (EARNER if tax else EARNER_UNTAXED) // 100
    pool = amount * ROYALTIES // 100
    to_treasury = amount - to_earner - pool
    split: dict[str, Micros] = {}
    weight = sum((royalties or {}).values())
    if weight:
        for author, w in sorted((royalties or {}).items()):
            split[author] = Micros(pool * w // weight)
        to_treasury += pool - sum(split.values())
    else:
        to_treasury += pool
    return RevenueSplit(Micros(to_earner), Micros(to_treasury), split)


def floor_top_up(*, purse: Micros, cap: Micros, treasury: Micros, budget: Micros) -> Micros | None:
    """The basic budget for a poor purse (below `cap`), 0 for one that isn't poor, or None when the treasury can't
    pay it (stop topping anyone up this cycle)."""
    if purse >= cap:
        return Micros(0)
    if treasury < budget:
        return None
    return budget


def members_to_wake(*, wanted: int, members: int, purse: Micros, upkeep: Micros) -> int:
    """As many as wanted, up to the members there are and what the purse can pay for."""
    return max(0, min(members, int(wanted), purse // upkeep))


def bond_for(reward: Micros, rate: float) -> Micros:
    """What a co-op posts on winning a claim: a share of the reward, returned when paid, forfeited if the job fails."""
    return Micros(round(reward * rate))
