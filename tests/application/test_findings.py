"""Findings kept across runs (docs/FINDINGS-PLAN.md F1-F2): a dossier per question, searchable, never a source."""

import json

from commons.application.actions import Actions
from commons.application.archive import Archive
from commons.application.services.findings import dossier, question_id
from commons.application.society import Params, World
from commons.domain.market import MarketJob, Part
from commons.domain.pack import load

Q = "[record] How many storm overflow spills did each English water company report in 2025?"
PAGE = ("https://www.gov.uk/government/news/fewer-and-shorter-storm-overflow-spills-in-2025",
        "Fewer and shorter storm overflow spills in 2025",
        "There were 291,492 monitored spills in 2025.\n\nSpill duration fell by a fifth.")


def society(tmp_path):
    pack = load("osint")
    archive = Archive(tmp_path / "archive")
    if not archive.passages:
        archive.add_page(*PAGE)
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, archive=archive,
              findings=tmp_path / "archive" / "findings")
    w.step()
    return w


def job(w, jid, analysis, check=None):
    prime = next(iter(w.communities))
    parts = {"analyse": Part("analyse", "s", "r", artifact=analysis, source="self")}
    if check:
        parts["verify"] = Part("verify", "s", "r", artifact=check, source="self", independent=True)
    return MarketJob(jid, Q, 1, parts, posted=0, deadline=9, prime=prime)


CITE = "[archive: web-www-gov-uk-government-news-fewer-and-shorter-storm-overflow-spills-in-2025#1]"
ANALYSIS = (f"Findings\nThere were 291,492 monitored spills in 2025 {CITE}. Duration fell by a fifth {CITE}.\n\n"
            "Confidence\nHigh: one official source.\n\nGaps\nPer-company counts aren't in the release.")


def test_a_questions_id_is_the_same_in_any_run():
    assert question_id(Q) == question_id("  " + Q.upper()) and question_id(Q).startswith("Q-")
    assert question_id(Q) != question_id(Q + " Why?")


def test_a_failure_then_a_paid_answer_build_one_dossier(tmp_path):
    w = society(tmp_path)
    w.findings.reasons["J1"] = {"analyse": "cites a passage that doesn't support the duration claim"}
    w.findings.record(job(w, "J1", ANALYSIS), paid=False, why="a part failed grading (analyse 0.40)")
    path = w.findings.record(job(w, "J7", ANALYSIS), paid=True, why="")
    text = path.read_text()
    assert text.startswith(f"# {question_id(Q)} · {Q}") and "Status: answered: verified on" in text
    assert "## Current best answer" in text and "## Verified findings" in text
    assert "There were 291,492 monitored spills in 2025" in text and CITE in text  # its source, there to follow
    assert "## Open gaps" in text and "Per-company counts aren't in the release." in text
    assert "cites a passage that doesn't support the duration claim" in text  # the lesson from the failure
    assert "| J1 | failed: a part failed grading" in text and "| J7 | paid |" in text
    state = json.loads(path.with_suffix(".json").read_text())
    assert dossier(state) == text  # written by rule: the same record, the same dossier


def test_a_claim_the_checker_contradicted_is_marked_so(tmp_path):
    w = society(tmp_path)
    check = f"Claim 2: duration fell by a fifth: contradicted by {CITE}\nSupported: 1 of 2. Contradicted: 1."
    text = w.findings.record(job(w, "J2", ANALYSIS, check), paid=False, why="the check found 1 contradicted").read_text()
    assert "## Contradicted findings" in text


def test_dossiers_are_searchable_now_and_in_the_next_run(tmp_path):
    w = society(tmp_path)
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    act = Actions(w, next(iter(w.communities.values())))
    assert question_id(Q).lower() in act.search_archive("storm overflow spills dossier verified findings").message
    later = society(tmp_path)  # a new run on the same society: its archive folder brings the dossier back
    assert any(p.source.startswith("findings/") for p in later.archive.passages.values())


def test_a_finding_is_never_a_source(tmp_path):
    w = society(tmp_path)
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    lead = next(pid for pid in w.archive.passages if pid.startswith("findings-"))
    prime = next(iter(w.communities))
    open_job = MarketJob("J9", Q, 1, {"analyse": Part("analyse", "s", "r")}, posted=w.cycle, deadline=w.cycle + 9,
                         prime=prime)
    open_job.status = "claimed"
    w.jobs["J9"] = open_job
    out = Actions(w, w.communities[prime]).do_part("J9", "analyse", f"Spills fell [archive: {lead}].")
    assert not out and "is a finding, not a source" in out.message
    assert w.grading.try_grade("s", "r", f"<q=0.9> spills [archive: {lead}]").score == 0


def test_a_question_worked_before_is_posted_as_an_update(tmp_path):
    """F3: the next run starts from the last one's findings instead of searching again."""
    w = society(tmp_path)
    w.findings.reasons["J1"] = {"analyse": "uncited confidence sentence"}
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    again = MarketJob("J8", Q, 1, {"collect": Part("collect", "Find public sources on this question.", "r"),
                                   "verify": Part("verify", "Check the work.", "r", independent=True)},
                      posted=0, deadline=9)
    assert w.findings.brief(again)
    spec = again.parts["collect"].spec
    assert spec.startswith("UPDATE: this question was worked on before (1 time; verified answer of")
    assert f'search_archive "{question_id(Q)}"' in spec and "Verified findings: 2" in spec
    assert "Per-company counts aren't in the release." in spec and spec.endswith("Find public sources on this question.")
    assert "Never cite the dossier itself" in spec
    fresh = MarketJob("J9", "[org] A question never asked", 1, {"collect": Part("collect", "Find.", "r")}, posted=0, deadline=9)
    assert not w.findings.brief(fresh) and fresh.parts["collect"].spec == "Find."


def test_open_questions_come_first_and_answered_ones_wait_thirty_days(tmp_path):
    """F4, your decision 12 Oct: refresh after 30 days."""
    import time as clock
    w = society(tmp_path)
    other = "[org] What did the Climate Change Committee report in 2025?"
    assert w.findings.due([Q, other], live=set()) == [Q, other]  # neither answered yet
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    assert w.findings.due([Q, other], live=set()) == [other]  # Q is answered and fresh
    assert w.findings.due([Q, other], live={other}) == []  # the other is on the board already: nothing to post
    later = clock.time() + 31 * 86_400
    assert w.findings.due([Q], live=set(), now=later) == [Q]  # its refresh is due


def test_a_follow_up_question_goes_to_your_gate_then_to_the_board(tmp_path):
    from commons.domain.gate import GatePolicy
    w = society(tmp_path)
    w.gate.policy = GatePolicy(govern="ask")
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")  # Q has a dossier: the society has it
    act = Actions(w, next(iter(w.communities.values())))
    follow = "[record] How many storm overflow spills did each water company report per site in 2025?"
    out = act.propose_question(follow, "the 2025 answer lacks per-company figures")
    assert out and "waiting for the operator" in out.message
    assert not act.propose_question(follow, "again")  # already proposed
    assert not act.propose_question(Q, "x")  # already one of the society's questions
    request = next(r for r in w.gate.pending() if r.tool == "propose_question")
    assert follow in request.detail and request.risk == "govern"
    w.web_desk.decide([request.id], True)
    w.step()  # approvals run at the start of the next cycle
    assert follow in (tmp_path / "questions.md").read_text() and follow in w.pack.work_source.subjects


def test_a_follow_up_about_a_person_is_refused(tmp_path):
    w = society(tmp_path)
    act = Actions(w, next(iter(w.communities.values())))
    out = act.propose_question("[person] Where does the chief executive live?", "x")
    assert not out and w.findings.proposed == {}


def test_only_societies_that_take_follow_ups_are_offered_the_tool():
    from commons.adapters.models import FakeBackend
    from commons.agents.llm.steward import LLMStrategy
    from commons.agents.llm.tools import TOOLS
    assert "propose_question" not in {t["name"] for t in TOOLS}  # not in the shared list: other packs unchanged
    assert load("osint").followups and not load("earn_online").followups


def test_an_update_is_paid_by_what_it_adds(tmp_path):
    """F5, your decision 12 Oct: re-confirming earns little; new findings and corrections earn in full."""
    from commons.application.services.findings import RECONFIRM
    w = society(tmp_path)
    assert w.findings.novelty(job(w, "J1", ANALYSIS)) is None  # a question's first answer is all new
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    assert w.findings.novelty(job(w, "J2", ANALYSIS)) == RECONFIRM  # the same two claims again
    newer = ANALYSIS.replace("Duration fell by a fifth", "Anglian Water reported the most spills")
    assert w.findings.novelty(job(w, "J3", newer)) == 0.5  # one claim of two is new
    j = job(w, "J4", newer)
    j.scores, j.novelty = {"analyse": 1.0}, 0.5
    assert j.value(quality_pay=0.5) == round(j.reward * 0.5)


def test_a_playbook_a_co_op_publishes_is_kept_for_later_runs(tmp_path):
    w = society(tmp_path)
    w.add_playbook("P1", next(iter(w.communities)), "collect", "Primary sources first", "Start from GOV.UK.")
    kept = list((tmp_path / "playbooks").glob("collect--primary-sources-first.md"))
    assert kept and "Start from GOV.UK." in kept[0].read_text()
    w.add_playbook("seed-x", "operator", "collect", "Seeded", "already yours")
    assert not list((tmp_path / "playbooks").glob("collect--seeded.md"))  # your own seeds aren't copied back


def test_findings_come_from_claims_not_from_notes_on_confidence_or_gaps(tmp_path):
    w = society(tmp_path)
    noisy = ANALYSIS.replace("High: one official source.", f"I am fairly confident in this {CITE}.").replace(
        "Per-company counts aren't in the release.", f"Per-company counts aren't in the release {CITE}.")
    state = w.findings.outcome(job(w, "J1", noisy), paid=True, why="")
    texts = [c["text"] for c in state["claims"]]
    assert len(texts) == 2 and all("confident" not in t and "Per-company" not in t for t in texts)
    assert any("Per-company counts" in g for g in state["gaps"])


def test_a_ticked_society_records_its_run_as_ticks(tmp_path):
    w = society(tmp_path)
    w.label_run("ticks")
    w.findings.record(job(w, "J1", ANALYSIS), paid=True, why="")
    assert "| ticks | J1 | paid |" in next((tmp_path / "archive" / "findings").glob("Q-*.md")).read_text()
