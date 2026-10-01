"""Ventures: rules refuse deterministically, the appraiser only scores, the market allocates by score."""

from commons.adapters.models import FakeBackend
from commons.agents.scripted import Strategy
from commons.application.actions import Actions
from commons.application.society import Params, World
from commons.application.ventures import LLMAppraiser
from commons.domain.community import Community
from commons.domain.ventures import StubAppraiser, Venture, similar, value


class Puppet(Strategy):
    name = "puppet"

    def wake(self, obs):
        return obs.members

    def turn(self, obs, act):
        return


GOOD = [{"capability": "research", "spec": "List five failure points of home espresso machines, one line each.",
         "rubric": "Exactly five lines; each names a specific component; no brand promotion."},
        {"capability": "write", "spec": "Write a 150-word maintenance guide for home espresso machines.",
         "rubric": "140 to 160 words; covers descaling, gaskets and grinder; no invented statistics."}]


def world(appraiser=None, **kw):
    pop = [Community("alpha", 3, {"research", "write"}, Puppet()), Community("beta", 3, {"research", "write"}, Puppet())]
    w = World(Params(seed=0, verify=False, **kw), population=pop, appraiser=appraiser)
    w.step()
    return w


def act(w, name):
    a = Actions(w, w.communities[name])
    a.me.capacity = 10
    return a


def test_an_approved_venture_becomes_the_proposers_job_at_a_market_price():
    w = world(StubAppraiser(8))
    before = w.ledger.balance("treasury")
    out = act(w, "alpha").propose_venture("Espresso care kit", "A guide for home baristas", GOOD)
    assert out and w.ledger.balance("treasury") == before + w.params.venture_fee
    w.step()
    v = w.ventures[out.id]
    assert v.status == "approved" and v.reward == value(8, w.params.job_reward, w.params.venture_min_score)
    job = w.jobs[v.job_id]
    assert job.prime == "alpha" and job.status == "claimed" and set(job.parts) == {"research", "write"}
    assert any(e.name == "venture.approved" and e.community == "alpha" for e in w.activity.ring)


def test_rules_refuse_before_any_appraisal():
    w = world()
    a = act(w, "alpha")
    assert "different capability" in a.propose_venture("x", "y", [GOOD[0], GOOD[0]]).message
    assert "unknown capability" in a.propose_venture("x", "y", [{**GOOD[0], "capability": "alchemy"}]).message
    assert "real spec and rubric" in a.propose_venture("x", "y", [{**GOOD[0], "rubric": "good"}]).message
    assert a.propose_venture("Espresso care kit", "pitch", GOOD)
    assert "already have a venture waiting" in a.propose_venture("Something else entirely", "p", GOOD).message
    assert "too close to existing work" in act(w, "beta").propose_venture("Espresso care kit", "copy", GOOD).message
    for _ in range(8):
        w.rep.attest("beta", "alpha", "research", 0.0)
    w2 = act(w, "alpha")
    assert "below the" in w2.propose_venture("New thing", "p", GOOD).message or "waiting" in w2.propose_venture("New thing", "p", GOOD).message


def test_low_scores_are_worth_nothing_and_rejected():
    w = world(StubAppraiser(3))
    vid = act(w, "alpha").propose_venture("Espresso care kit", "pitch", GOOD).id
    w.step()
    assert w.ventures[vid].status == "rejected" and w.ventures[vid].reward == 0 and not w.ventures[vid].job_id


def test_the_market_takes_the_best_scored_first_not_the_first_asked():
    class ByTitle:
        def appraise(self, v):
            from commons.domain.ventures import Appraisal
            return Appraisal(9 if "best" in v.title else 6, "scored by title")

    w = world(ByTitle(), venture_budget=1)
    first = act(w, "alpha").propose_venture("An early average venture about bicycles", "p", GOOD).id
    best = act(w, "beta").propose_venture("The best venture about kitchen knives", "p", GOOD).id
    w.step()
    assert w.ventures[best].status == "approved" and w.ventures[first].status == "pending"
    w.step()
    assert w.ventures[first].status == "approved"  # its turn came when the budget freed up


def test_the_appraiser_only_scores_and_code_holds_it_to_its_findings():
    def answer(**kw):
        base = {"reason": "r", "coherent": True, "gradeable": True, "padded": False, "manipulation_attempt": False, "score": 9}
        return FakeBackend(respond=lambda *a: {**base, **kw})

    v = Venture("P1", "alpha", "t", "p", [("write", "spec " * 10, "rubric " * 10)], 1)
    assert LLMAppraiser(answer()).appraise(v).score == 9
    assert LLMAppraiser(answer(gradeable=False)).appraise(v).score == 4
    assert LLMAppraiser(answer(padded=True)).appraise(v).score == 4
    assert LLMAppraiser(answer(manipulation_attempt=True)).appraise(v).score == 0
    backend = answer()
    LLMAppraiser(backend).appraise(v)
    assert "<proposal>" in backend.calls[0][1] and "untrusted" in backend.calls[0][0]


def test_an_unavailable_appraiser_leaves_the_proposal_waiting():
    class Down:
        def appraise(self, v):
            from commons.domain.ventures import AppraisalError
            raise AppraisalError("model not loaded")

    w = world(Down())
    vid = act(w, "alpha").propose_venture("Espresso care kit", "p", GOOD).id
    w.step()
    assert w.ventures[vid].status == "pending" and w.ventures[vid].score is None


def test_ventures_are_logged_and_the_books_balance():
    w = world(StubAppraiser(7))
    act(w, "alpha").propose_venture("Espresso care kit", "p", GOOD)
    w.step()
    names = {e.name for e in w.activity.ring}
    assert {"propose_venture", "venture.proposed", "venture.approved"} <= names
    w.ledger.check()


def test_similarity_is_word_overlap():
    assert similar("Espresso care kit", "espresso CARE kit!") == 1.0
    assert similar("Espresso care kit", "Bicycle repair guide") == 0.0
