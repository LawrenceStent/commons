"""The wall between created money (SIM) and real money (USD)."""

import pytest

from commons.domain.compute import Usage, cost_micros
from commons.substrate.ledger import SIM, USD, InsufficientFunds, Ledger, WrongCurrency, purse
from commons.substrate.meter import KillSwitch, Meter

CALL = Usage(input_tokens=10_000, output_tokens=2_000)
COST = cost_micros("claude-haiku-4-5", CALL)  # 20_000 micro-dollars


def test_sim_money_cannot_touch_real_accounts_or_the_reverse():
    led = Ledger()
    with pytest.raises(WrongCurrency):
        led.transfer("ext:stripe", purse("a"), 100, cycle=0, kind="x")
    with pytest.raises(WrongCurrency):
        led.transfer("market", purse("a"), 100, cycle=0, kind="x", currency=USD)
    with pytest.raises(WrongCurrency):
        led.transfer("genesis", "treasury", 100, cycle=0, kind="x", currency=USD)


def test_balances_are_per_currency():
    led = Ledger()
    led.transfer("genesis", purse("a"), 700, cycle=0, kind="genesis")
    led.transfer("owner:capital", purse("a"), 5, cycle=0, kind="capital", currency=USD)
    assert led.balance(purse("a")) == 700 and led.balance(purse("a"), USD) == 5
    with pytest.raises(InsufficientFunds):  # 700 created credits don't make 6 real dollars
        led.transfer(purse("a"), purse("b"), 6, cycle=1, kind="x", currency=USD)
    led.check()


def test_real_revenue_needs_a_real_source():
    led = Ledger(currency=USD)
    with pytest.raises(WrongCurrency):
        led.settle_revenue("a", 1000, cycle=1)
    led.settle_revenue("a", 1000, cycle=1, source="ext:stripe")
    assert led.balance(purse("a")) == 700 and led.balance("treasury") == 300
    assert led.real()["revenue"] == 1000
    led.check()


def test_real_api_calls_in_a_simulation_are_recorded_in_usd():
    led = Ledger()
    led.transfer("genesis", purse("a"), 10**6, cycle=0, kind="genesis")
    m = Meter(led, daily_ceiling=10**12)
    m.charge_usage("a", "claude-haiku-4-5", CALL, cycle=1, real=False)  # local model: notional only
    assert led.real()["api_spend"] == 0
    m.charge_usage("a", "claude-haiku-4-5", CALL, cycle=1, real=True)
    assert led.balance(purse("a")) == 10**6 - 2 * COST  # notional, in credits
    assert led.real() == {"capital_in": COST, "revenue": 0, "api_spend": COST, "fees": 0}
    assert m.real_spent_total() == COST
    led.check()


def test_real_ceiling_trips_after_recording_the_spend():
    led = Ledger()
    led.transfer("genesis", purse("a"), 10**6, cycle=0, kind="genesis")
    m = Meter(led, daily_ceiling=10**12, real_ceiling=COST * 2)
    m.charge_usage("a", "claude-haiku-4-5", CALL, cycle=1, real=True)
    with pytest.raises(KillSwitch):
        m.charge_usage("a", "claude-haiku-4-5", CALL, cycle=1, real=True)
    assert m.halted and led.real()["api_spend"] == 2 * COST
    m.reset()
    assert m.real_spent_today == 2 * COST  # a reset doesn't forget real money


def test_live_society_pays_the_real_bill_from_purses_once():
    led = Ledger(currency=USD)
    led.add_capital(10**6, cycle=0, to=purse("a"))
    m = Meter(led, daily_ceiling=10**12)
    m.charge_usage("a", "claude-haiku-4-5", CALL, cycle=1, real=True)
    assert led.balance(purse("a")) == 10**6 - COST
    assert led.real() == {"capital_in": 10**6, "revenue": 0, "api_spend": COST, "fees": 0}
    assert led.total(SIM) == 0
    led.check()
