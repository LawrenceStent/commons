"""The turn-based engine: the contract-net across cycles, its deadlines, and what each side sees."""


from commons.agents.scripted import Strategy
from commons.application.actions import Actions
from commons.application.society import Params, World
from commons.domain.community import Community
from commons.domain.grading import tagged
from commons.domain.market import MarketJob, Part
from commons.substrate.ledger import purse


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
    # these tests are about contracts and deadlines, so claims are instant here; allocation has its own tests
    w = World(Params(**{"seed": 0, "verify": False, "claim_allocation": False, **kw}), population=pop)
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
    w = world(grader_reviews=False)  # with prime reviews, the prime sees the delivery to review it
    job = claimed_job_needing_build(w)
    c = announce_and_award(w, job)
    act(w, "sub").deliver(c.id, tagged(0.9, " work"))
    prime, sub, other = (w.observe(w.communities[n]) for n in ("prime", "sub", "other"))
    assert prime.to_review[0].artifact and prime.to_review[0].bids
    assert not other.to_review and not other.to_deliver
    assert all(v.bids == () for v in sub.to_deliver + sub.open_contracts)


def test_the_grader_accepts_a_good_delivery_and_its_grade_counts_for_the_job():
    w = world()
    job = claimed_job_needing_build(w)
    c = announce_and_award(w, job)
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    assert c.status == "delivered" and c.id in w.grading.pending_reviews
    w.grading.settle()
    assert c.status == "accepted" and "passed grading" in c.reason
    assert job.parts["build"].artifact and job.scores["build"] == 0.9
    assert w.rep.score("prime", "sub", "build") > 0.5
    before = w.ledger.balance(purse("prime"))
    act(w, "prime").do_part(job.id, "research", tagged(0.9, " research"))
    graded = []
    real_grade = w.grader.grade
    w.grader.grade = lambda *a: graded.append(a) or real_grade(*a)
    w.grading.settle()
    assert len(graded) == 1  # only research: the build part's delivery grade was reused
    assert job.status == "paid" and w.jobs_done == 1 and w.ledger.balance(purse("prime")) > before
    w.ledger.check()


def test_the_grader_rejects_a_bad_delivery_and_the_prime_pays_nothing_more():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, tagged(0.2, " junk"))
    sub_before = w.ledger.balance(purse("sub"))
    w.grading.settle()
    assert c.status == "rejected" and "failed grading" in c.reason
    assert w.ledger.balance(purse("sub")) == sub_before
    assert w.rep.score("prime", "sub", "build") < 0.5


def test_reviews_and_disputes_are_no_longer_the_primes_to_make():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    assert "grader judges" in act(w, "prime").review(c.id, False).message
    assert "judged by the grader" in act(w, "sub").dispute(c.id, "unfair").message
    assert not w.observe(w.communities["prime"]).to_review


def test_a_grader_outage_accepts_the_delivery_by_default_after_retries():
    w = world(grade_retries=2)
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, "untagged text the stub can't read")

    from commons.application.graders import GradingError

    def down(*a):
        raise GradingError("model not loaded")

    w.grader.grade = down
    w.grading.settle()
    assert c.status == "delivered"
    w.grading.settle()
    assert c.status == "accepted" and "grader was unavailable" in c.reason


def test_a_prime_that_cannot_pay_for_passing_work_defaults():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    act(w, "sub").deliver(c.id, tagged(0.9, " build"))
    w.ledger.transfer(purse("prime"), "compute", w.ledger.balance(purse("prime")), cycle=w.cycle, kind="test")
    w.grading.settle()
    assert c.status == "defaulted" and w.rep.score("sub", "prime", "build") < 0.5


def test_undelivered_work_fails_and_the_prime_complaint_is_filed():
    w = world()
    c = announce_and_award(w, claimed_job_needing_build(w))
    for _ in range(w.params.deliver_ttl + 1):
        w.step()
    assert c.status == "failed"
    assert w.rep.score("prime", "sub", "build") < 0.5


def test_unreviewed_delivery_is_accepted_by_default():
    w = world(grader_reviews=False)
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


def test_doing_a_part_yourself_closes_its_open_contracts():
    w = world()
    job = MarketJob("T2", "kit", 80_000, {"research": Part("research", "do research", "rubric")},
                    posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    assert act(w, "prime").claim(job.id)
    cid = act(w, "prime").announce(job.id, "research", 30_000, 0.5).id
    assert act(w, "prime").do_part(job.id, "research", "done it myself")
    c = w.contracts[cid]
    assert c.status == "withdrawn" and c.closed == w.cycle
    assert [e.fields["stage"] for e in w.hub.recent("contract.stage") if e.fields["id"] == cid][-1] == "withdrawn"


def test_a_hand_in_that_breaks_the_parts_format_is_refused_by_rule():
    from commons.application.commands.base import FORMAT_REFUSED
    from commons.domain.format import Format

    w = world()
    fmt = Format(max_words=5, sections=("Risks",))
    job = MarketJob("T3", "kit", 80_000, {c: Part(c, f"do {c}", "rubric", format=fmt) for c in ("research", "build")},
                    posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    assert act(w, "prime").claim(job.id)
    capacity = w.communities["prime"].capacity
    out = act(w, "prime").do_part(job.id, "research", "far too many words for this part to be accepted")
    assert not out and out.id == FORMAT_REFUSED and "the most is 5" in out.message and "Risks" in out.message
    assert job.parts["research"].artifact is None and w.communities["prime"].capacity == capacity  # nothing used
    assert act(w, "prime").do_part(job.id, "research", "Risks\nfew words")
    # a contractor's delivery meets the same rule
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert act(w, "sub").bid(cid, 20_000)
    w.step()
    assert act(w, "prime").award(cid, "sub")
    refused = act(w, "sub").deliver(cid, "no risks section in this delivery at all")
    assert not refused and refused.id == FORMAT_REFUSED
    assert act(w, "sub").deliver(cid, "Risks\nbuilt it")


def test_scripted_stand_ins_are_judged_by_their_tag_not_the_format():
    from commons.domain.format import Format

    w = world()
    job = MarketJob("T4", "kit", 80_000, {"research": Part("research", "do it", "rubric", format=Format(min_words=100))},
                    posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    assert act(w, "prime").claim(job.id)
    assert act(w, "prime").do_part(job.id, "research", tagged(0.9, " research"))


def test_a_co_op_with_no_capacity_left_cannot_act():
    """Since Phase 1 this check never fired (a refusing Outcome is falsy, so `if err := ...` skipped it); 3 Oct."""
    w = world()
    job = claimed_job_needing_build(w)
    w.communities["prime"].capacity = 0
    out = act(w, "prime").do_part(job.id, "research", "x")
    assert not out and "no capacity left" in out.message and job.parts["research"].artifact is None


def test_citing_a_playbook_that_does_not_exist_is_refused():
    w = world()
    job = claimed_job_needing_build(w)
    out = act(w, "prime").do_part(job.id, "research", "x", cites=("PB999",))
    assert not out and "unknown playbook" in out.message and job.parts["research"].artifact is None


def test_work_over_the_size_cap_is_refused_not_cut_off():
    from commons.application.commands.base import FORMAT_REFUSED, MAX_ARTIFACT

    w = world()
    job = claimed_job_needing_build(w)
    long = "word " * (MAX_ARTIFACT // 5 + 1)
    out = act(w, "prime").do_part(job.id, "research", long)
    assert not out and out.id == FORMAT_REFUSED and f"the most is {MAX_ARTIFACT}" in out.message
    assert job.parts["research"].artifact is None
    fits = "x" * MAX_ARTIFACT
    assert act(w, "prime").do_part(job.id, "research", fits) and job.parts["research"].artifact == fits  # whole
    assert not act(w, "prime").publish("research", "a method", long)


def test_an_independent_part_is_bought_from_someone_who_did_no_other_part():
    w = world()
    job = MarketJob("T5", "kit", 80_000, {"research": Part("research", "r", "r"),
                                          "build": Part("build", "b", "b"),
                                          "write": Part("write", "w", "w", independent=True)},
                    posted=w.cycle, deadline=w.cycle + 6)
    w.jobs[job.id] = job
    assert act(w, "prime").claim(job.id)
    w.communities["prime"].capabilities = frozenset({"research", "write"})
    out = act(w, "prime").do_part(job.id, "write", "x")
    assert not out and "another co-op" in out.message  # the prime can't check its own work
    build = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert act(w, "sub").bid(build, 20_000)
    w.step()
    assert act(w, "prime").award(build, "sub")
    write = act(w, "prime").announce(job.id, "write", 30_000, 0.5).id
    out = act(w, "sub").bid(write, 20_000)  # sub holds the build part
    assert not out and "no other part" in out.message
    w.communities["other"].capabilities = frozenset({"build", "write"})
    assert act(w, "other").bid(write, 20_000)
    w.step()
    assert act(w, "prime").award(write, "other")
    assert job.independence_refusal("research", "other", w.contracts) == \
        "you hold job T5's independent part, so you can't take another part of it"
