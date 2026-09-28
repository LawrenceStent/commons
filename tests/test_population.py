"""Spawn, retire, fork, merge, learn and disputes: each has a check that stops one community
from doing it alone or cheaply."""

from sim.actions import Actions
from sim.engine import Params, World
from sim.market import MarketJob, Part, tagged
from society.community import Community
from society.strategies import Strategy
from substrate.ledger import purse


class Puppet(Strategy):
    name = "puppet"

    def wake(self, obs) -> int:
        return obs.members

    def turn(self, obs, act) -> None:
        return


def world(**kw) -> World:
    pop = [Community("alpha", 3, {"research", "build"}, Puppet()), Community("beta", 2, {"build", "write"}, Puppet()),
           Community("gamma", 2, {"design"}, Puppet())]
    w = World(Params(**{"seed": 0, "verify": False, "claim_allocation": False, **kw}), population=pop)
    for c in pop:
        w.ledger.transfer("genesis", purse(c.name), 5_000_000, cycle=0, kind="genesis")
    w.step()
    return w


def act(w: World, name: str) -> Actions:
    return Actions(w, w.communities[name])


# ── spawn / retire ─────────────────────────────────────────────
def test_spawn_needs_a_second_from_someone_else_and_pays_the_treasury():
    w = world()
    pid = act(w, "alpha").propose_spawn("analyst").id
    assert "different community" in act(w, "alpha").second_spawn(pid).message
    assert any(r.id == pid for r in w.observe(w.communities["beta"]).spawn_requests)
    treasury = w.ledger.balance("treasury")
    assert act(w, "beta").second_spawn(pid)
    assert w.communities["alpha"].members == 4
    assert w.ledger.balance("treasury") == treasury + w.params.spawn_fee


def test_unseconded_spawn_expires():
    w = world()
    pid = act(w, "alpha").propose_spawn("analyst").id
    for _ in range(w.params.spawn_window + 1):
        w.step()
    assert w.proposals[pid].status == "expired" and w.communities["alpha"].members == 3
    assert not act(w, "beta").second_spawn(pid)


def test_member_limit_and_retire():
    w = world(max_members=3)
    assert "fork instead" in act(w, "alpha").propose_spawn("x").message
    assert act(w, "alpha").retire() and w.communities["alpha"].members == 2
    act(w, "gamma").retire()
    assert "at least one member" in act(w, "gamma").retire().message


# ── fork ───────────────────────────────────────────────────────
def test_fork_takes_members_a_purse_share_and_capabilities():
    w = world()
    before = w.ledger.balance(purse("alpha"))
    out = act(w, "alpha").fork("alpha-labs", 1, ("research",), "research only")
    assert out, out.message
    child = w.communities["alpha-labs"]
    assert child.members == 1 and w.communities["alpha"].members == 2
    assert child.capabilities == {"research"} and child.parent == "alpha"
    assert w.ledger.balance(purse("alpha-labs")) == before // 3
    w.step()  # the child takes turns from the next cycle
    assert w.history["alpha-labs"] and w.communities["alpha-labs"].active
    w.ledger.check()


def test_fork_rules():
    w = world()
    assert "someone has to stay" in act(w, "gamma").fork("g2", 2, ("design",), "").message
    assert "subset" in act(w, "gamma").fork("g2", 1, ("write",), "").message
    assert "already exists" in act(w, "gamma").fork("beta", 1, ("design",), "").message
    assert "lowercase" in act(w, "gamma").fork("Bad Name", 1, ("design",), "").message


def test_forking_cannot_launder_a_bad_record():
    w = world()
    for _ in range(6):
        w.rep.attest("beta", "alpha", "research", 0.0)
    for _ in range(6):
        w.rep.attest("gamma", "alpha", "research", 1.0)
    act(w, "alpha").fork("alpha-new", 1, ("research",), "")
    parent = w.rep.standing("alpha")
    child = w.rep.standing("alpha-new")
    assert child < parent  # half the good, all the bad


# ── merge ──────────────────────────────────────────────────────
def test_merge_needs_both_sides_and_moves_everything():
    w = world()
    act(w, "gamma").publish("design", "how we design", "sketch three options, pick one")
    moved = w.ledger.balance(purse("gamma"))
    pid = act(w, "gamma").propose_merge("beta").id
    assert "addressed to you" in act(w, "alpha").accept_merge(pid).message
    target_purse = w.ledger.balance(purse("beta"))
    assert act(w, "beta").accept_merge(pid)
    beta, gamma = w.communities["beta"], w.communities["gamma"]
    assert gamma.dissolved and beta.members == 4 and "design" in beta.capabilities
    assert w.ledger.balance(purse("beta")) == target_purse + moved
    assert all(pb.author == "beta" for pb in w.library.values())
    w.step()
    assert not gamma.active and all(p.name != "gamma" for p in w.observe(beta).peers)


def test_merge_waits_for_work_in_flight():
    w = world()
    job = MarketJob("T1", "kit", 80_000, {"design": Part("design", "d", "r")}, posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    act(w, "gamma").claim(job.id)
    pid = act(w, "gamma").propose_merge("beta").id
    assert "in flight" in act(w, "beta").accept_merge(pid).message


# ── learn ──────────────────────────────────────────────────────
def test_learning_costs_more_for_generalists_and_pays_the_playbook_author():
    w = world()
    pid = act(w, "beta").publish("write", "writing", "lead with the benefit").id
    before = w.ledger.balance(purse("beta"))
    assert act(w, "gamma").learn("write", pid)
    assert "write" in w.communities["gamma"].capabilities
    assert w.ledger.balance(purse("beta")) == before + round(w.params.learn_cost * w.params.learn_royalty)
    spent = w.meter.by_community["alpha"]
    assert act(w, "alpha").learn("design")  # a third capability: the base price
    assert act(w, "alpha").learn("write")  # a fourth: double
    assert w.meter.by_community["alpha"] - spent == 3 * w.params.learn_cost
    assert "already have" in act(w, "alpha").learn("design").message
    assert "anyone trades" in act(w, "alpha").learn("juggling").message


# ── disputes ───────────────────────────────────────────────────
def rejected_contract(w: World, quality: float):
    job = MarketJob("T9", "kit", 80_000, {c: Part(c, f"do {c}", "rubric") for c in ("research", "write")},
                    posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    act(w, "alpha").claim(job.id)
    cid = act(w, "alpha").announce(job.id, "write", 30_000, 0.5).id
    act(w, "beta").bid(cid, 20_000)
    w.step()
    act(w, "alpha").award(cid, "beta")
    act(w, "beta").deliver(cid, tagged(quality, " copy"))
    act(w, "alpha").review(cid, False, "not good enough")
    return job, w.contracts[cid]


def test_a_false_rejection_is_overturned_and_costs_the_prime():
    w = world(grader_reviews=False)  # the prime-review path, kept as an option
    job, c = rejected_contract(w, 0.9)
    assert any(x.id == c.id for x in w.observe(w.communities["beta"]).to_dispute)
    prime_before, sub_before = w.ledger.balance(purse("alpha")), w.ledger.balance(purse("beta"))
    out = act(w, "beta").dispute(c.id, "it meets the rubric")
    assert out and "filed" in out.message
    assert c.status == "rejected"  # decided after the turns, outside the lock
    w.settle_grading()
    assert c.status == "accepted" and job.parts["write"].artifact
    owed = c.price - c.advance
    assert w.ledger.balance(purse("alpha")) == prime_before - owed - w.params.audit_cost
    assert w.ledger.balance(purse("beta")) == sub_before + owed  # fee paid, then reimbursed
    assert w.rep.standing("alpha") < 0.5
    assert "already been audited" in act(w, "beta").dispute(c.id, "again").message
    w.ledger.check()


def test_a_fair_rejection_is_upheld_and_the_disputer_pays():
    w = world(grader_reviews=False)
    _, c = rejected_contract(w, 0.2)
    before = w.ledger.balance(purse("beta"))
    assert act(w, "beta").dispute(c.id, "it's fine really")
    w.settle_grading()
    assert c.status == "rejected" and w.ledger.balance(purse("beta")) == before - w.params.audit_cost
    assert any(e.kind == "audit" and "upheld" in e.text for e in w.inbox["beta"])


def test_disputes_close_after_the_window():
    w = world(grader_reviews=False)
    _, c = rejected_contract(w, 0.9)
    for _ in range(w.params.dispute_window + 1):
        w.step()
    assert not w.observe(w.communities["beta"]).to_dispute
    assert "too late" in act(w, "beta").dispute(c.id, "late").message or "no rejected" in act(w, "beta").dispute(c.id, "late").message
