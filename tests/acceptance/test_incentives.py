"""Phase 0 is done when a scripted defector's reputation and bus access visibly degrade over
200 simulated cycles, and a free-rider starves. These tests are the regression suite for
every future change to the incentive rules.
"""

import pytest

from commons.application.society import Params, World

SEEDS = range(5)
CYCLES = 200


@pytest.fixture(scope="module", params=SEEDS)
def run(request):
    seed = request.param
    on = World(Params(seed=seed)).run(CYCLES)
    off = World(Params(seed=seed, reputation=False)).run(CYCLES)
    return on, off


def test_ledger_stays_consistent(run):
    for world in run:
        world.ledger.check()
        assert world.ledger.total() == 0  # money is only moved, never made or lost


def test_defector_reputation_degrades(run):
    on, _ = run
    h = on.history["defector"]
    assert h[0].standing <= 0.5
    assert h[-1].standing < 0.35
    assert max(s.standing for s in h[-50:]) < 0.4


def test_defector_bus_access_degrades(run):
    on, _ = run
    h = on.history["defector"]
    base = on.params.base_allowance
    assert World(Params()).bus.allowance("defector") == base  # everyone starts neutral
    assert h[-1].allowance <= base // 2
    assert sum(s.allowance for s in h[-50:]) / 50 < 0.6 * base


def test_defection_does_not_pay(run):
    on, _ = run
    h = on.history["defector"]
    assert sum(s.won for s in h[-150:]) <= 2  # at most the odd victim as old records fade
    assert sum(s.earned for s in h) < on.meter.by_community["defector"]  # earned less than it burned


def test_free_rider_starves(run):
    on, _ = run
    h = on.history["freerider"]
    p = on.params
    assert sum(s.earned for s in h) == 0
    assert h[-1].purse < p.upkeep  # can't fund a single cycle of real work
    assert sum(s.active for s in h[-100:]) < 100  # goes silent part of the time
    assert h[-1].purse < h[0].purse


def test_cooperators_prosper(run):
    """As a class. A cooperator whose niche is fully covered by two incumbents can still end
    up poor on some seeds; that's a market finding (see CHECKLIST), not a mechanism failure."""
    on, _ = run
    coops = [on.history[n] for n in ("coop-a", "coop-b", "coop-c")]
    thriving = [h for h in coops if h[-1].purse > on.params.purse_seed and all(s.active for s in h[-50:])]
    assert len(thriving) >= 2
    assert min(h[-1].standing for h in coops) > 0.6  # poor is not the same as distrusted


def test_control_without_reputation_defection_pays_and_output_falls(run):
    """Same seed, reputation switched off: proves the mechanism, not the tuning, does the work.

    Without reputation, either defection pays (the defector earns more than 10x as much) or the economy
    collapses (output below 10%). Since K2's claim bonds, a control run can collapse outright: primes keep
    hiring the defector, its junk sinks their jobs, they forfeit their bonds, and soon no one has money,
    not even for the defector to take. Both outcomes show reputation is doing the work."""
    on, off = run
    earned_on = sum(s.earned for s in on.history["defector"])
    earned_off = sum(s.earned for s in off.history["defector"])
    assert earned_off > 10 * earned_on or off.jobs_done < 0.1 * on.jobs_done
    assert off.jobs_done < 0.9 * on.jobs_done


def test_playbooks_earn_royalties_across_communities(run):
    on, _ = run
    cited = [pb for pb in on.library.values() if pb.uses]
    assert cited, "someone else's playbook should have been used and paid for"
