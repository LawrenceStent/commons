"""R5.2: the treasury's rules as pure functions: the revenue split, the floor, waking members, claim bonds."""

from commons.domain.treasury import bond_for, floor_top_up, members_to_wake, revenue_split


def test_revenue_splits_70_20_10_and_royalties_go_to_cited_authors():
    s = revenue_split(100_000, {"lab": 2, "studio": 1}, tax=True)
    assert s.earner == 70_000 and s.royalties == {"lab": 6_666, "studio": 3_333}
    assert s.treasury == 20_000 + 1  # the royalty slice's remainder goes to the treasury
    assert s.earner + s.treasury + sum(s.royalties.values()) == 100_000


def test_no_citations_send_the_royalty_slice_to_the_treasury_and_no_tax_gives_it_to_the_earner():
    assert revenue_split(100_000, {}, tax=True) == (70_000, 30_000, {})
    untaxed = revenue_split(100_000, {}, tax=False)
    assert (untaxed.earner, untaxed.treasury) == (90_000, 10_000)


def test_the_floor_tops_up_only_the_poor_and_only_while_the_treasury_can():
    assert floor_top_up(purse=1_000, cap=8_000, treasury=50_000, budget=3_000) == 3_000
    assert floor_top_up(purse=8_000, cap=8_000, treasury=50_000, budget=3_000) == 0
    assert floor_top_up(purse=1_000, cap=8_000, treasury=2_000, budget=3_000) is None  # the treasury is spent: stop


def test_members_wake_as_wanted_up_to_what_the_purse_can_pay():
    assert members_to_wake(wanted=3, members=3, purse=20_000, upkeep=4_000) == 3
    assert members_to_wake(wanted=3, members=3, purse=9_000, upkeep=4_000) == 2
    assert members_to_wake(wanted=5, members=2, purse=99_000, upkeep=4_000) == 2
    assert members_to_wake(wanted=-1, members=2, purse=99_000, upkeep=4_000) == 0


def test_a_claim_bond_is_a_share_of_the_reward():
    assert bond_for(80_000, 0.1) == 8_000 and bond_for(80_000, 0.0) == 0
