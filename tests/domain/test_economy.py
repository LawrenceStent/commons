"""R5.1: how passing work is paid, as a policy chosen once. Adding an economy means adding one class."""

import pytest

from commons.domain.economy import GrantPayment, MarketPayment, policy_for


def test_a_market_pays_at_once_from_outside():
    m = MarketPayment()
    assert m.pays_at_once and m.pool is None and m.source is None and m.payer == "the market"
    assert m.funding(0) == 0 and m.view(0) is None


def test_grants_are_topped_up_to_at_most_a_few_budgets():
    g = GrantPayment(budget=100_000, cap_cycles=3)
    assert not g.pays_at_once and g.pool == "grants" and g.source == "grants" and g.payer == "the grants"
    assert g.funding(0) == 100_000
    assert g.funding(250_000) == 50_000  # room for only half a budget
    assert g.funding(300_000) == 0
    assert GrantPayment(budget=0, cap_cycles=3).funding(0) == 0


def test_scarce_grants_are_shared_by_value_and_plentiful_ones_pay_in_full():
    g = GrantPayment(budget=100_000, cap_cycles=3)
    values = {"A": 80_000, "B": 60_000}
    assert g.shares(values, pool=100_000) == {"A": 80_000 * 100_000 // 140_000, "B": 60_000 * 100_000 // 140_000}
    assert g.shares(values, pool=500_000) == values
    assert sum(g.shares(values, pool=99_999).values()) <= 99_999


def test_what_stewards_are_told():
    assert GrantPayment(budget=600_000, cap_cycles=3).view(1_200_000) == (1_200_000, 600_000)
    assert "grants" in GrantPayment(1, 1).queued


def test_the_policy_is_chosen_once_from_the_settings():
    assert isinstance(policy_for("market", 0, 3), MarketPayment)
    g = policy_for("grant", 120_000, 3)
    assert isinstance(g, GrantPayment) and (g.budget, g.cap_cycles) == (120_000, 3)
    with pytest.raises(ValueError, match="no economy called"):
        policy_for("barter", 0, 3)


def test_a_new_economy_is_one_class():
    """A patron who pays a flat 50,000 for any passing job, at once: no other code changes."""
    from dataclasses import dataclass

    from commons.application.world import Params, World

    @dataclass(frozen=True)
    class Patron:
        name: str = "patron"
        pays_at_once: bool = False  # queue, then pay flat shares at the end of the cycle
        pool: str | None = "grants"
        funder: str | None = "funder"
        source: str | None = "grants"
        payer: str = "the patron"
        queued: str = "the patron pays at the end of the cycle"

        def funding(self, pool_balance):
            return 1_000_000 - pool_balance

        def shares(self, values, pool):
            return {jid: 50_000 for jid in values}

        def view(self, pool_balance):
            return (pool_balance, 1_000_000)

    w = World(Params(seed=0), payment=Patron()).run(30)
    paid = [e.fields["payout"] for e in w.hub.recent("market.job", n=500) if e.fields["stage"] == "paid"]
    assert paid and set(paid) == {50_000}
    w.ledger.check()
