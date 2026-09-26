"""The turn-based engine: the contract-net across cycles, its deadlines, and what each side sees."""

import pytest

from sim.actions import Actions
from sim.engine import Params, World
from sim.market import MarketJob, Part, tagged
from society.community import Community
from society.strategies import Strategy
from substrate.ledger import purse


class Puppet(Strategy):
    """Wakes everyone and does nothing; tests act for it."""

    name = "puppet"

    def wake(self, obs) -> int:
        return obs.members

    def turn(self, obs, act) -> None:
        return


def world(**kw) -> World:
    pop = [Community("prime", 2, {"research"}, Puppet()), Community("sub", 2, {"build", "write", "design"}, Puppet()),
           Community("other", 2, {"build"}, Puppet())]
    w = World(Params(seed=0, verify=False, **kw), population=pop)
    w.step()
    return w


def act(w: World, name: str) -> Actions:
    return Actions(w, w.communities[name])


def claimed_job_needing_build(w: World):
    """A research + build job: prime does research and must buy build."""
    job = MarketJob("T1", "test kit", 80_000, {c: Part(c, f"do {c}", f"{c} rubric") for c in ("research", "build")},
                    posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    assert act(w, "prime").claim(job.id)
    return job


def announce_and_award(w: World, job, bidder="sub", price=20_000):
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert act(w, bidder).bid(cid, price)
    assert not act(w, "prime").award(cid, bidder)  # same cycle: others haven't had a turn to bid
    w.step()
    assert act(w, "prime").award(cid, bidder)
    return w.contracts[cid]


def test_outcomes_explain_refusals():
    w = world()
    job = claimed_job_needing_build(w)
    assert "lack the build" in act(w, "prime").do_part(job.id, "build", "x").message
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert "your own contract" in act(w, "prime").bid(cid, 10).message
    assert "between 1 and 30000" in act(w, "sub").bid(cid, 40_000).message
    assert "not on the board" in act(w, "sub").claim(job.id).message


def test_only_the_prime_sees_bids_and_deliveries():
    w = world()
    job = claimed_job_needing_build(w)
    c = announce_and_award(w, job)
    act(w, "sub").deliver(c.id, tagged(0.9, " work"))
    prime, sub, other = (w.observe(w.communities[n]) for n in ("prime", "sub", "other"))
    assert prime.to_review[0].artifact and prime.to_review[0].bids
    assert not other.to_review and not other.to_deliver
    assert all(v.bids == () for v in sub.to_deliver + sub.open_contracts)


def test_accepted_delivery_completes_the_job_and_the_market_pays():
    w = world()
    job = claimed_job_needing_build(w)
    c = announce_and_award(w, job)
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    before = w.ledger.balance(purse("prime"))
    act(w, "prime").do_part(job.id, "research", tagged(0.9, " research"))
    assert act(w, "prime").review(c.id, True)
    assert job.status == "claimed" and job.id in w.awaiting_grade  # submitted; graded after the turns
    w.settle_grading()
    assert job.status == "paid" and w.jobs_done == 1
    assert w.ledger.balance(purse("prime")) > before
    assert w.rep.score("prime", "sub", "build") > 0.5
    w.ledger.check()


def test_a_bad_part_fails_grading_and_nobody_is_paid_for_the_job():
    w = world()
    job = claimed_job_needing_build(w)
    c = announce_and_award(w, job)
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    act(w, "prime").review(c.id, True)
    act(w, "prime").do_part(job.id, "research", tagged(0.2, " sloppy"))
    w.settle_grading()
    assert job.status == "failed" and w.jobs_done == 0


def test_undelivered_work_fails_and_the_prime_complaint_is_filed():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    for _ in range(w.params.deliver_ttl + 1):
        w.step()
    assert c.status == "failed"
    assert w.rep.score("prime", "sub", "build") < 0.5


def test_unreviewed_delivery_is_accepted_by_default():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    for _ in range(w.params.review_ttl + 1):
        w.step()
    assert c.status == "accepted" and "by default" in c.reason
    settled = w.ledger.db.execute("SELECT count(*) FROM entries WHERE memo = ?", (f"settle {c.id}",)).fetchone()[0]
    assert settled == 1


def test_a_prime_that_cannot_pay_defaults_and_is_rated_for_it():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    drain = w.ledger.balance(purse("prime"))
    w.ledger.transfer(purse("prime"), "compute", drain, cycle=w.cycle, kind="test")
    for _ in range(w.params.review_ttl + 1):
        w.step()
    assert c.status == "defaulted"
    assert w.rep.score("sub", "prime", "build") < 0.5


def test_same_seed_same_world():
    a, b = (World(Params(seed=7, verify=False)).run(150) for _ in range(2))
    assert [s.purse for s in a.history["coop-a"]] == [s.purse for s in b.history["coop-a"]]
    assert a.jobs_done == b.jobs_done


def test_closed_jobs_and_contracts_are_dropped_so_memory_stays_flat():
    w = World(Params(seed=0, verify=False)).run(400)
    assert len(w.jobs) < 80 and len(w.contracts) < 80
    assert all(len(q) <= w.params.events_keep for q in w.inbox.values())


def test_a_community_cannot_hoard_jobs():
    w = world()  # prime has 2 members, both awake
    ids = []
    for n in range(3):
        job = MarketJob(f"H{n}", "kit", 80_000, {"research": Part("research", "r", "r")}, posted=w.cycle, deadline=w.cycle + 3)
        w.jobs[job.id] = job
        ids.append(job.id)
    act(w, "prime").me.capacity = 10
    assert act(w, "prime").claim(ids[0]) and act(w, "prime").claim(ids[1])
    out = act(w, "prime").claim(ids[2])
    assert not out and "finish one first" in out.message


def test_the_world_refuses_bids_from_the_distrusted():
    w = world()
    job = claimed_job_needing_build(w)
    for _ in range(6):
        w.rep.attest("other", "sub", "build", 0.0)  # the commons has seen sub fail repeatedly
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    out = act(w, "sub").bid(cid, 20_000)
    assert not out and "standing" in out.message and "sub" not in w.contracts[cid].bids
    assert act(w, "other").bid(cid, 25_000)


def test_the_world_refuses_an_award_when_standing_fell_after_the_bid():
    w = world()
    job = claimed_job_needing_build(w)
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert act(w, "sub").bid(cid, 20_000)
    for _ in range(6):
        w.rep.attest("prime", "sub", "build", 0.0)  # the prime's own record of sub in build collapses
    w.step()
    view = next(c for c in w.observe(w.communities["prime"]).my_announcements if c.id == cid)
    assert not view.bids[0].eligible and "below the 0.35 line" in view.bids[0].refused_because
    out = act(w, "prime").award(cid, "sub")
    assert not out and "refuses this award" in out.message and w.contracts[cid].status == "open"


def test_the_control_run_refuses_no_one():
    w = world(reputation=False)
    for _ in range(6):
        w.rep.attest("other", "sub", "build", 0.0)
    assert w.eligible("prime", "sub", "build") == (True, "")
