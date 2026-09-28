"""K2: no rule rewards being first. Claims are allocated by rule, bonds make hoarding unprofitable, pay
scales with quality, and outcomes known only later can settle later."""

from sim.actions import Actions
from sim.engine import Params, World
from sim.market import Grade, MarketJob, Part, StubGrader, tagged
from society.community import Community
from society.strategies import Cooperator, Strategy
from substrate.ledger import purse


class Puppet(Strategy):
    name = "puppet"

    def wake(self, obs):
        return obs.members

    def turn(self, obs, act):
        return


def world(pop=None, **kw) -> World:
    pop = pop or [Community("a", 2, {"research"}, Puppet()), Community("b", 2, {"research"}, Puppet()),
                  Community("c", 2, {"research", "write"}, Puppet())]
    w = World(Params(**{"seed": 0, "verify": False, **kw}), population=pop)
    w.step()
    return w


def job(w, jid="K1", caps=("research",), reward=80_000):
    j = MarketJob(jid, "kit", reward, {c: Part(c, f"do {c}", "rubric") for c in caps}, posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[j.id] = j
    return j


def act(w, name):
    a = Actions(w, w.communities[name])
    a.me.capacity = 10
    return a


def test_the_first_to_claim_does_not_win_the_most_trusted_does():
    w = world()
    j = job(w)
    for _ in range(4):
        w.rep.attest("c", "b", "research", 1.0)  # b has a track record; a doesn't
    assert act(w, "a").claim(j.id)  # a asks first
    assert act(w, "b").claim(j.id)
    assert j.status == "open"  # nothing is decided mid-cycle
    w._allocate_claims()
    assert j.prime == "b" and j.status == "claimed"
    assert any(e.kind == "claim_lost" and "went to b" in e.text for e in w.inbox["a"])


def test_ties_go_to_the_better_fit_then_a_seeded_draw_never_arrival_order():
    w = world()
    j = job(w, caps=("research", "write"))
    act(w, "a").claim(j.id)
    act(w, "c").claim(j.id)  # c can do both parts
    w._allocate_claims()
    assert j.prime == "c"
    results = set()
    for order in (("a", "b"), ("b", "a")):
        w2 = world()
        j2 = job(w2)
        for name in order:
            act(w2, name).claim(j2.id)
        w2._allocate_claims()
        results.add(j2.prime)
    assert len(results) == 1  # the same winner whichever asked first


def test_the_bond_is_escrowed_returned_when_paid_and_forfeited_when_the_job_fails():
    w = world()
    good, bad = job(w, "G1"), job(w, "B1")
    for jid in ("G1", "B1"):
        act(w, "a").claim(jid)
    before = w.ledger.balance(purse("a"))
    w._allocate_claims()
    bond = round(80_000 * w.params.claim_bond)
    assert w.ledger.balance("escrow") == 2 * bond and w.ledger.balance(purse("a")) == before - 2 * bond
    act(w, "a").do_part("G1", "research", tagged(0.9, " good"))
    w.settle_grading()
    assert good.status == "paid" and w.ledger.balance("escrow") == bond
    treasury = w.ledger.balance("treasury")
    for _ in range(w.params.job_ttl + 1):
        w.step()
    assert bad.status == "failed" and w.ledger.balance("escrow") == 0
    assert w.ledger.balance("treasury") >= treasury + bond - 20 * w.params.basic_budget  # the bond went to the commons
    w.ledger.check()


class Hoarder(Strategy):
    """Claims every job it may and never does the work."""
    name = "hoarder"

    def wake(self, obs):
        return obs.members

    def turn(self, obs, act):
        for j in obs.board:
            act.claim(j.id)


def test_hoarding_is_unprofitable():
    pop = [Community("hoarder", 3, {"research", "build", "design", "write"}, Hoarder()),
           Community("coop-x", 3, {"research", "build"}, Cooperator()), Community("coop-y", 3, {"design", "write"}, Cooperator())]
    w = World(Params(seed=1, verify=False), population=pop).run(150)
    h, x = w.history["hoarder"], w.history["coop-x"]
    forfeited = w.ledger.db.execute(
        "select coalesce(sum(p.amount), 0) from postings p join entries e on e.id = p.entry_id "
        "where e.kind = 'bond' and e.memo like 'forfeit%' and p.account = 'treasury'").fetchone()[0]
    assert forfeited > 0  # it lost bonds on jobs it never did
    assert h[-1].purse < h[0].purse and h[-1].purse < x[-1].purse
    assert sum(s.earned for s in h) == 0


def test_pay_scales_with_quality():
    for score, share in ((1.0, 1.0), (0.6, 0.8)):
        w = world(claim_allocation=False, claim_bond=0)
        j = job(w, reward=100_000)
        act(w, "a").claim(j.id)
        act(w, "a").do_part(j.id, "research", tagged(score, " work"))
        w.settle_grading()
        paid = [e.fields["payout"] for e in w.hub.recent("market.job", n=20) if e.fields.get("stage") == "paid"]
        assert paid == [round(100_000 * share)]


class Delayed(StubGrader):
    """A grader whose verdict is known only later (a trading P&L, a verified claim)."""
    def __init__(self, later=None):
        super().__init__()
        self.later = later

    def grade(self, spec, rubric, artifact):
        g = super().grade(spec, rubric, artifact)
        return Grade(g.score, g.cost, "provisional", settle_after=3)

    def settle(self, job):
        return self.later


def test_deferred_outcomes_hold_the_money_until_they_settle():
    w = World(Params(seed=0, verify=False, claim_allocation=False), grader=Delayed(),
              population=[Community("a", 2, {"research"}, Puppet())])
    w.step()
    j = job(w)
    act(w, "a").claim(j.id)
    act(w, "a").do_part(j.id, "research", tagged(0.9, " work"))
    w.settle_grading()
    assert j.status == "graded" and j.id in w.deferred and w.jobs_done == 0
    for _ in range(3):
        w.step()
    assert j.status == "paid" and j.id not in w.deferred


def test_a_deferred_outcome_can_turn_out_badly():
    w = World(Params(seed=0, verify=False, claim_allocation=False), grader=Delayed(later={"research": 0.2}),
              population=[Community("a", 2, {"research"}, Puppet())])
    w.step()
    j = job(w)
    act(w, "a").claim(j.id)
    act(w, "a").do_part(j.id, "research", tagged(0.9, " work"))
    for _ in range(4):
        w.step()
    assert j.status == "failed"


def test_efficiency_is_earned_against_spent_and_each_coop_sees_its_own():
    from runtime.render import render

    w = World(Params(seed=0, verify=False)).run(60)
    e = w.efficiency("coop-a")
    assert e["spent"] > 0 and e["ratio"] == round(e["earned"] / e["spent"], 3)
    assert "Efficiency: earned" in render(w.observe(w.communities["coop-a"]))
    assert w.efficiency("freerider")["earned"] == 0
