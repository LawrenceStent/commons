"""K6/T5: performance per horizon, deterministic: return against an equal-weight buy-and-hold benchmark, maximum
drawdown and Sortino, a risk-adjusted score, and the credits it earns (nothing for a score at or below zero)."""

import pytest

from packs.trading.performance import benchmark, max_drawdown, payout, score, sortino


def test_benchmark_is_equal_weight_buy_and_hold_from_the_window_start():
    start = {"A": 100.0, "B": 50.0}
    assert benchmark(start, {"A": 110.0, "B": 45.0}) == pytest.approx((0.10 - 0.10) / 2)
    assert benchmark(start, {"A": 120.0}) == pytest.approx((0.20 + 0.0) / 2)  # no new quote: unchanged


def test_max_drawdown_is_the_worst_fall_from_a_peak():
    assert max_drawdown([100, 110, 99, 105, 88, 120]) == pytest.approx(1 - 88 / 110)
    assert max_drawdown([100, 101, 102]) == 0.0


def test_sortino_penalises_only_the_falls():
    assert sortino([100, 101, 102, 103]) is None  # no downside: undefined
    steady = sortino([100, 102, 101, 103, 102, 104])
    choppy = sortino([100, 108, 95, 106, 92, 104])
    assert steady > choppy


def test_the_score_is_excess_return_less_half_the_drawdown():
    s = score([10_000, 10_300, 10_100, 10_400], bench=0.01)
    assert s.ret == pytest.approx(0.04) and s.excess == pytest.approx(0.03)
    assert s.drawdown == pytest.approx(1 - 10_100 / 10_300) and s.value == pytest.approx(0.03 - s.drawdown / 2)


def test_pay_follows_a_positive_score_only():
    assert payout(0.02, per_return=100_000_000) == 2_000_000
    assert payout(0.0, per_return=100_000_000) == 0 and payout(-0.05, per_return=100_000_000) == 0
