"""Performance, per horizon: deterministic, never a model's opinion (FRAMEWORK.md §7.2).

Over each window of H cycles, a co-op's account is judged on its return net of costs (fees and slippage are already
in the account's value) against a benchmark: the same capital held equally across the universe from the window's
start, untouched. Risk counts: the score is the excess return less half the maximum drawdown, and the Sortino ratio
is reported beside it. A positive score earns credits for thinking (`payout`); nothing else does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def benchmark(start: dict[str, float], now: dict[str, float]) -> float:
    """Equal-weight buy and hold from `start`; a symbol with no new price hasn't moved."""
    if not start:
        return 0.0
    return sum(now.get(s, p) / p - 1 for s, p in start.items()) / len(start)


def max_drawdown(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = max(worst, 1 - v / peak)
    return worst


def sortino(values: list[float]) -> float | None:
    """Mean step return over the downside deviation (no annualising: windows are compared with each other)."""
    steps = [b / a - 1 for a, b in zip(values, values[1:])]
    downside = [min(0.0, r) ** 2 for r in steps]
    if not steps or not any(downside):
        return None
    return (sum(steps) / len(steps)) / math.sqrt(sum(downside) / len(steps))


@dataclass(frozen=True)
class Score:
    ret: float
    bench: float
    excess: float
    drawdown: float
    sortino: float | None
    value: float  # excess less half the drawdown: what is paid for


def score(values: list[float], bench: float) -> Score:
    ret = values[-1] / values[0] - 1
    dd = max_drawdown(values)
    return Score(ret, bench, ret - bench, dd, sortino(values), (ret - bench) - dd / 2)


def payout(value: float, per_return: int) -> int:
    """Credits (µcr) for a score: `per_return` for a score of 1.0 (100 points), pro rata; nothing at or below zero."""
    return max(0, round(value * per_return))
