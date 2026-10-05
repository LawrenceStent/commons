"""K6/T8.3: the graduation criteria, written before results, judged by code."""

import pickle

from packs.trading.broker import Account
from packs.trading.desk import TradingDesk
from packs.trading.graduation import MIN_WINDOWS, judge, ticks_played
from packs.trading.prices import FakeMarket


def desk_with(windows, *, stopped=False, pauses=0):
    d = TradingDesk(FakeMarket())
    d.accounts["a"] = Account(10_000, 10_000, stopped=stopped, pauses=pauses)
    d.settlements = [{"coop": "a", **w} for w in windows]
    return d


GOOD = {"excess": 0.004, "score": 0.002, "drawdown": 0.02}
BAD = {"excess": -0.003, "score": -0.006, "drawdown": 0.03}


def test_a_desk_that_meets_every_criterion_graduates():
    v = judge(desk_with([GOOD] * 40 + [BAD] * 20), "a")
    assert v.graduates and v.reasons == ()


def test_each_criterion_can_fail_it():
    assert "windows settled" in judge(desk_with([GOOD] * (MIN_WINDOWS - 1)), "a").reasons[0]
    assert any("mean excess" in r for r in judge(desk_with([GOOD] * 20 + [BAD] * 40), "a").reasons)
    assert any("score positive" in r for r in judge(desk_with([GOOD] * 30 + [{**BAD, "excess": 0.02}] * 30), "a").reasons)
    assert any("drawdown" in r for r in judge(desk_with([GOOD] * 59 + [{**GOOD, "drawdown": 0.12}]), "a").reasons)
    assert "met the kill criterion" in judge(desk_with([GOOD] * 60, stopped=True), "a").reasons
    assert any("daily loss" in r for r in judge(desk_with([GOOD] * 60, pauses=4), "a").reasons)


def test_ticks_played_counts_skips_against_it():
    log = ["2026-10-05 10:00:00 tick: paper", "2026-10-05 11:00:00 skip: 40% memory free", "2026-10-05 12:00:00 tick: paper"]
    assert ticks_played(log) == 2 / 3 and ticks_played([]) is None


def test_an_account_saved_before_pauses_were_counted_loads_with_none():
    a = Account(10_000, 10_000)
    state = dict(a.__dict__)
    del state["pauses"]
    old = Account.__new__(Account)
    old.__setstate__(state)
    assert old.pauses == 0 and pickle.loads(pickle.dumps(a)).pauses == 0
