"""K6/T3: the paper broker's rules, in code from day one (FRAMEWORK.md §7.2): a stop with every buy, a cap on each
position, no shorting or leverage, a daily loss pause and a kill criterion. Pure: no prices fetched, no world."""

import pytest

from packs.trading.broker import Account, Costs, Limits, Quote

COSTS = Costs(fee=0.001, slippage=0.0005)
LIMITS = Limits()


def q(price, symbol="BTC-USD", fresh=True):
    return Quote(symbol, price, at=0.0, fresh=fresh)


def account(capital=10_000.0):
    return Account(capital=capital, cash=capital)


def test_a_buy_fills_at_the_quote_plus_slippage_less_its_fee():
    a = account()
    ok, msg = a.buy("BTC-USD", 1_000, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    assert ok, msg
    p = a.positions["BTC-USD"]
    assert p.entry == pytest.approx(100.05) and p.qty == pytest.approx((1_000 - 1.0) / 100.05)
    assert p.stop == pytest.approx(100.05 * 0.95) and a.cash == pytest.approx(9_000) and a.fees == pytest.approx(1.0)


@pytest.mark.parametrize("stop_pct,why", [(None, "stop"), (0.0, "stop"), (0.005, "1%"), (0.2, "15%")])
def test_every_buy_needs_a_stop_between_1_and_15_percent(stop_pct, why):
    ok, msg = account().buy("BTC-USD", 1_000, stop_pct=stop_pct, quote=q(100.0), costs=COSTS, limits=LIMITS)
    assert not ok and why in msg


def test_no_position_over_a_fifth_of_the_account_and_no_leverage():
    a = account()
    ok, msg = a.buy("BTC-USD", 2_500, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    assert not ok and "20%" in msg
    assert a.buy("BTC-USD", 1_900, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)[0]
    ok, msg = a.buy("BTC-USD", 500, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)  # adds up past 20%
    assert not ok and "20%" in msg
    small = account(1_000)
    small.cash = 100
    ok, msg = small.buy("ETH-USD", 150, stop_pct=0.05, quote=q(10.0, "ETH-USD"), costs=COSTS, limits=LIMITS)
    assert not ok and "cash" in msg


def test_no_shorting_and_selling_what_you_hold_returns_cash():
    a = account()
    ok, msg = a.sell("BTC-USD", None, quote=q(100.0), costs=COSTS)
    assert not ok and "hold no" in msg
    a.buy("BTC-USD", 1_000, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    held = a.positions["BTC-USD"].qty
    ok, msg = a.sell("BTC-USD", held * 2, quote=q(110.0), costs=COSTS)
    assert not ok and "more than" in msg
    assert a.sell("BTC-USD", None, quote=q(110.0), costs=COSTS)[0]
    assert "BTC-USD" not in a.positions and a.cash > 10_000 - 1_000 + 1_000  # sold at a profit


def test_stale_quotes_refuse_orders():
    ok, msg = account().buy("SPY", 1_000, stop_pct=0.05, quote=q(500.0, "SPY", fresh=False), costs=COSTS, limits=LIMITS)
    assert not ok and "closed" in msg


def test_stops_only_move_up_and_stay_within_the_band():
    a = account()
    a.buy("BTC-USD", 1_000, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    ok, msg = a.set_stop("BTC-USD", 0.10, quote=q(100.0), limits=LIMITS)  # lower than the stop it has
    assert not ok and "only be raised" in msg
    assert a.set_stop("BTC-USD", 0.02, quote=q(120.0), limits=LIMITS)[0]
    assert a.positions["BTC-USD"].stop == pytest.approx(120 * 0.98)


def test_a_stop_is_hit_on_a_fresh_quote_only():
    a = account()
    a.buy("BTC-USD", 1_000, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    assert a.mark({"BTC-USD": q(90.0, fresh=False)}, day="d1", costs=COSTS, limits=LIMITS) == []
    assert "BTC-USD" in a.positions
    told = a.mark({"BTC-USD": q(90.0)}, day="d1", costs=COSTS, limits=LIMITS)
    assert "BTC-USD" not in a.positions and any("stop" in t for t in told)


def test_a_bad_day_closes_everything_and_pauses_trading_until_the_next():
    a = account()
    a.mark({}, day="d1", costs=COSTS, limits=LIMITS)
    for s in ("A", "B"):
        a.buy(s, 1_900, stop_pct=0.15, quote=q(100.0, s), costs=COSTS, limits=LIMITS)
    told = a.mark({"A": q(88.0, "A"), "B": q(88.0, "B")}, day="d1", costs=COSTS, limits=LIMITS)  # -12% on 38%: ~-4.6%
    assert not a.positions and a.paused == "d1" and any("daily loss" in t for t in told)
    ok, msg = a.buy("A", 100, stop_pct=0.05, quote=q(88.0, "A"), costs=COSTS, limits=LIMITS)
    assert not ok and "paused" in msg
    a.mark({}, day="d2", costs=COSTS, limits=LIMITS)
    assert a.buy("A", 100, stop_pct=0.05, quote=q(88.0, "A"), costs=COSTS, limits=LIMITS)[0]


def test_down_a_fifth_of_capital_stops_trading_for_good():
    a = account()
    a.cash = 7_900  # losses so far
    told = a.mark({}, day="d1", costs=COSTS, limits=LIMITS)
    assert a.stopped and any("kill" in t for t in told)
    ok, msg = a.buy("A", 100, stop_pct=0.05, quote=q(10.0, "A"), costs=COSTS, limits=LIMITS)
    assert not ok and "stopped" in msg


def test_value_marks_positions_at_their_last_known_price():
    a = account()
    a.buy("BTC-USD", 1_000, stop_pct=0.05, quote=q(100.0), costs=COSTS, limits=LIMITS)
    held = a.positions["BTC-USD"].qty
    assert a.value({"BTC-USD": q(120.0)}) == pytest.approx(9_000 + held * 120.0)
    assert a.value({}) == pytest.approx(9_000 + held * 100.0)  # no quote: the last price it saw
