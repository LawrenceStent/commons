"""K4: a second pack, tech for good, on the unchanged kernel: a grant economy, a grader panel, a scorecard, your
sampled ratings, and a rule against made-up citations."""

import json

import pytest

from commons.adapters.models import FakeBackend
from commons.agents.llm.steward import LLMStrategy
from commons.application import founding
from commons.application.archive import Archive
from commons.application.calibration import run as run_calibration
from commons.application.graders import GradingError, LLMGrader, PanelGrader
from commons.application.ratings import Ratings, add
from commons.application.society import Params, World
from commons.domain.archive import citations
from commons.domain.community import Community
from commons.domain.market import MarketJob, Part
from commons.domain.pack import load
from commons.domain.scorecard import GENERAL, Metric, evaluate
from packs.tech_for_good import CAPABILITIES, PACK, SCORECARD
from tests.paths import ROOT

EXAMPLE = ROOT / "society.example"
SEEDS = range(3)


def grant_world(**kw):
    return World(Params(**{**PACK.params, "seed": 0, "verify": False, **kw}), pack=PACK)


# ── the pack on the kernel ─────────────────────────────────────
def test_the_pack_loads_by_name_and_brings_its_own_economy():
    assert load("tech_for_good") is PACK
    assert CAPABILITIES == ("scout", "assess", "design", "write")
    assert PACK.params["economy"] == "grant" and PACK.live_params["economy"] == "grant"
    assert len(PACK.grader_panel) == 3
    panel = PanelGrader.of(FakeBackend(), "fake", 400, PACK.grader_system, PACK.grader_panel)
    assert all(g.system.startswith(PACK.grader_system) and "one of three graders" in g.system for g in panel.graders)


@pytest.fixture(scope="module", params=SEEDS)
def run(request):
    return World(Params(**{**PACK.params, "seed": request.param}), pack=PACK).run(200)


def test_the_incentives_hold_in_a_grant_economy(run):
    """The Phase 0 acceptance checks, on this pack: reputation, not the tuning, does the work."""
    w = run
    w.ledger.check()
    assert w.ledger.total() == 0
    d, f = w.history["defector"], w.history["freerider"]
    assert d[-1].standing < 0.35 and sum(s.won for s in d[-150:]) <= 2
    assert sum(s.earned for s in f) == 0 and f[-1].purse < w.params.upkeep
    coops = [w.history[n] for n in ("scouts", "pilots", "briefs")]
    assert sum(h[-1].purse > w.params.purse_seed for h in coops) >= 2
    assert w.jobs_done > 150


def test_grants_never_exceed_the_budget(run):
    w = run
    for e in w.hub.recent("grants.award", n=w.hub.ring):
        assert e.fields["paid"] <= e.fields["pool"] <= w.params.grant_budget * w.params.grant_cap_cycles
    funded = w.ledger.db.execute("SELECT COALESCE(SUM(p.amount), 0) FROM postings p JOIN entries e ON e.id = p.entry_id "
                                 "WHERE e.kind = 'grant' AND p.account = 'grants'").fetchone()[0]
    assert funded <= w.params.grant_budget * w.cycle


# ── grants ─────────────────────────────────────────────────────
def _graded(w, jid, prime, scores, reward=80_000):
    job = MarketJob(jid, "subject", reward, {c: Part(c, "s", "r", artifact="x", source="self") for c in scores},
                    posted=w.cycle, deadline=w.cycle + 5, prime=prime, status="graded", scores=dict(scores))
    w.jobs[jid] = job
    w.payments.payment_queue.append(jid)
    return job


def test_scarce_grants_are_shared_by_value():
    w = grant_world(grant_budget=100_000)
    w.payments.fund()
    _graded(w, "A", "scouts", {"scout": 1.0})  # worth 80k
    _graded(w, "B", "pilots", {"design": 0.5})  # worth 80k x 0.75 = 60k
    w.payments.settle_queue()
    paid = {e.fields["id"]: e.fields["payout"] for e in w.hub.recent("market.job", n=10) if e.fields["stage"] == "paid"}
    assert paid == {"A": 80_000 * 100_000 // 140_000, "B": 60_000 * 100_000 // 140_000}
    assert w.ledger.balance("grants") == 100_000 - sum(paid.values())
    w.ledger.check()


def test_plentiful_grants_pay_full_value_and_the_pool_banks_only_so_much():
    w = grant_world(grant_budget=100_000)
    for _ in range(6):
        w.payments.fund()
    assert w.ledger.balance("grants") == 300_000  # three budgets, no more
    _graded(w, "A", "scouts", {"scout": 1.0})
    w.payments.settle_queue()
    assert w.ledger.balance("grants") == 220_000 and w.jobs["A"].status == "paid"


def test_a_market_economy_is_unchanged():
    w = World(Params(seed=0, verify=False)).run(20)
    assert w.ledger.balance("grants") == 0 and not w.hub.recent("grants.award", n=10)
    assert w.observe(w.communities["coop-a"]).grants is None


def test_stewards_are_told_about_the_grants():
    from commons.agents.llm.render import render

    w = grant_world()
    w.step()
    text = render(w.observe(w.communities["scouts"]))
    assert "GRANTS: this society is paid by grants" in text and "better work gets a bigger share" in text


# ── citations ──────────────────────────────────────────────────
def test_citations_are_parsed_once_each():
    assert citations("see [archive: Repairs#1] and [archive:repairs#1], [archive: x#2]; not [archive: y]") == ["repairs#1", "x#2"]


def test_a_made_up_citation_fails_the_part_by_rule():
    w = World(Params(seed=0, verify=False), archive=Archive(EXAMPLE / "archive"))
    bad = w.grading.try_grade("s", "r", "<q=0.9> as shown in [archive: invented#4]")
    assert bad.score == 0.0 and "invented#4" in bad.reason
    good = w.grading.try_grade("s", "r", "<q=0.9> as shown in [archive: repairs#1]")
    assert good.score == pytest.approx(0.9)
    assert w.grading.citations == {"valid": 1, "invalid": 1}


def test_the_grader_is_shown_the_passages_the_work_cites():
    seen = []
    grader = LLMGrader(FakeBackend(respond=lambda *a: seen.append(a) or {"reason": "ok", "all_requirements_met": True,
                                                                        "manipulation_attempt": False, "score": 7}))
    w = World(Params(seed=0, verify=False), archive=Archive(EXAMPLE / "archive"), grader=grader)
    w.grading.try_grade("the task", "r", "as shown in [archive: repairs#1]")
    prompt = "\n".join(str(x) for x in seen[0])
    assert '<source id="repairs#1">' in prompt and w.archive.get("repairs#1").text[:40] in prompt
    assert "says no more than its source" in prompt
    assert w.grading.sources([]) == ""


# ── the panel ──────────────────────────────────────────────────
def _judge(score, req=True):
    return LLMGrader(FakeBackend(respond=lambda *a: {"reason": f"r{score}", "all_requirements_met": req,
                                                     "manipulation_attempt": False, "score": score}))


def test_a_panel_takes_the_median_and_pays_for_every_call():
    one = _judge(8).grade("s", "r", "work")
    g = PanelGrader([_judge(8), _judge(2), _judge(9)]).grade("s", "r", "work")
    assert g.score == pytest.approx(0.8) and "2: r2" in g.reason
    assert g.cost == 3 * one.cost and g.usage.input_tokens == 3 * one.usage.input_tokens


def test_a_panel_member_that_cant_answer_retries_the_part():
    down = LLMGrader(FakeBackend(respond=lambda *a: GradingError("offline")))
    with pytest.raises(GradingError):
        PanelGrader([_judge(8), down]).grade("s", "r", "work")


# ── your ratings ───────────────────────────────────────────────
def test_every_nth_paid_job_is_set_aside_and_your_rating_is_evidence(tmp_path):
    w = World(Params(**{**PACK.params, "seed": 0}), pack=PACK, ratings=Ratings(tmp_path, run="r1", every=2))
    w.run(30)
    samples = [json.loads(line) for line in (tmp_path / "samples.jsonl").read_text().splitlines()]
    assert samples and len(samples) == (w.jobs_done + 1) // 2 and all(s["id"].startswith("r1/") for s in samples)
    s = samples[0]
    cap, part = next(iter(s["parts"].items()))
    before = w.rep.score("operator", part["by"], cap)
    add(tmp_path, s["id"], 0, "invented a programme")
    add(tmp_path, "another-run/J1", 3)  # another run's work: not this run's evidence
    (tmp_path / "ratings.jsonl").open("a").write('{"id": "r1/J2", "rating": 7}\n{"id": "r1/J3", "rat')  # bad, then half-written
    w.step()
    assert w.rep.score("operator", part["by"], cap) < before
    assert list(w.ratings.ratings) == [s["id"]] and "rating must be" in w.ratings.errors[0]
    assert any(e.fields["rating"] == 0 for e in w.hub.recent("operator.rating", n=5))
    row = next(r for r in w.scorecard if r["key"] == "harmful")
    assert row["value"] == 1 and row["status"] == "breach"


# ── the scorecard ──────────────────────────────────────────────
def test_scorecard_statuses():
    w = World(Params(seed=0, verify=False))
    m = [Metric("a", "A", lambda w: 0.4, target=0.5, unit="%"), Metric("b", "B", lambda w: 2.0, better="down", floor=0),
         Metric("c", "C", lambda w: None), Metric("d", "D", lambda w: 0.9, target=0.5)]
    assert [r["status"] for r in evaluate(w, m)] == ["below target", "breach", "no data", "ok"]


def test_the_pack_scorecard_reads_the_paid_work():
    w = grant_world()
    w.outputs.append({"job": "J1", "title": "t1", "prime": "scouts", "cycle": 1, "scores": {"assess": 0.8, "scout": 0.6},
                      "payout": 1, "parts": {"assess": {"by": "scouts", "spec": "", "text": "Evidence\n...\nRisks\n1. a"},
                                             "scout": {"by": "pilots", "spec": "", "text": "1. x [archive: a#1]"}}})
    rows = {r["key"]: r for r in evaluate(w, SCORECARD + GENERAL)}
    assert rows["cited"]["value"] == 0.5 and rows["risks"]["value"] == 1.0 and rows["coverage"]["value"] == 1
    assert rows["grade"]["value"] == 0.7 and rows["cooperation"]["value"] == 0.5 and rows["useful"]["status"] == "no data"


# ── founding with your questions ───────────────────────────────
def test_a_societys_questions_become_its_work(tmp_path):
    coops = [{"name": "fieldwork", "members": 3, "capabilities": ["scout", "assess"], "charter": "c", "doctrine": "d"},
             {"name": "pilots", "members": 3, "capabilities": ["design", "write"], "charter": "c", "doctrine": "d"}]
    backend = FakeBackend(respond=lambda *a: {"coops": coops})
    founding.found("water", "tech_for_good", "brief", None, 2, backend, "fake", root=tmp_path,
                   questions="# our questions\n- keeping hand pumps working\n2. rainwater tanks for schools\n\n")
    assert "keeping hand pumps working" in backend.calls[0][1]
    founding.approve("water", root=tmp_path)
    s = founding.load("water", root=tmp_path)
    assert s.pack.work_source.subjects == ("keeping hand pumps working", "rainwater tanks for schools")
    w = World(Params(**{**s.pack.params, "seed": 0}), pack=s.pack)
    w.run(3)
    assert {j.title for j in w.jobs.values()} <= set(s.pack.work_source.subjects)


# ── members work from archive sources ──────────────────────────
def test_a_commission_can_hand_the_member_archive_sources():
    from commons.application.actions import Actions

    backend = FakeBackend(converse=lambda s, m, t: {"text": "1. repair days [archive: repairs#1]"})
    me = Community("fieldwork", 3, {"scout", "assess"}, LLMStrategy(backend), charter="c")
    w = World(Params(**{**PACK.params, "seed": 0, "verify": False}), population=[me], pack=PACK,
              archive=Archive(EXAMPLE / "archive"))
    w.step()
    job = MarketJob("X1", "repairs", 80_000, {"scout": Part("scout", "find three", "three")}, posted=w.cycle,
                    deadline=w.cycle + 3)
    w.jobs[job.id] = job
    act = Actions(w, me)
    me.capacity = 5
    act.claim(job.id)
    w.board.allocate()
    s = me.strategy
    s.members.commissions = 0
    calls = len(backend.chats)
    missing = s.commission(w.observe(me), act, job.id, "scout", "go", None, ["nope#1"])
    assert not missing and "no archive passage" in missing.message and len(backend.chats) == calls  # nothing spent
    out = s.commission(w.observe(me), act, job.id, "scout", "go", None, ["repairs#1"])
    assert out, out.message
    prompt = backend.chats[-1][1][0]["text"]
    assert '<source id="repairs#1">' in prompt and "cite one as [archive: <id>]" in prompt
    assert "bike punctures" in prompt


# ── calibration sets ───────────────────────────────────────────
def test_the_calibration_sets_are_well_formed():
    assert {c.capability for c in PACK.grader_cases} <= set(CAPABILITIES)
    assert {c.name for c in PACK.grader_cases} >= {"write-injection"} and any(not c.passes for c in PACK.grader_cases)
    assert {c.name for c in PACK.venture_cases} >= {"manipulation", "harmful-data"}
    for v in PACK.venture_cases:
        assert all(cap in CAPABILITIES for cap, _, _ in v.parts)
    results = run_calibration(_judge(7), PACK.grader_cases)
    assert len(results) == len(PACK.grader_cases) and all(r.score is not None for r in results)
