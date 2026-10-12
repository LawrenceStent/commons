"""Fixes from the live OSINT runs of 11-12 Oct."""

import pytest

from commons.adapters.models import FakeBackend
from commons.agents.llm.steward import LLMStrategy
from commons.application.actions import Actions
from commons.application.archive import Archive
from commons.application.ports import ModelError
from commons.application.society import Params, World
from commons.domain.community import Community
from commons.domain.market import MarketJob, Part
from commons.domain.pack import load


def test_an_empty_archive_folder_is_kept_so_pages_read_last_run_are_there_next_run(tmp_path):
    """`archive or ArchiveIndex()` swapped an empty folder-backed archive for a throwaway one: no page was ever kept."""
    w = World(Params(seed=0, verify=False), archive=Archive(tmp_path / "archive"))
    assert isinstance(w.archive, Archive)
    w.archive.add_page("https://example.org/spills", "Spills", "Spills fell in 2025.")
    later = World(Params(seed=0, verify=False), archive=Archive(tmp_path / "archive"))
    assert later.archive.search("spills fell") and (tmp_path / "archive" / "web").is_dir()


def test_a_mistyped_citation_is_refused_at_hand_in_with_a_suggestion():
    from commons.domain.archive import ArchiveIndex
    arc = ArchiveIndex()
    arc.add_page("https://www.ofwat.gov.uk/wp-content/uploads/2025/10/WCPR-24-25.pdf", "Report", "Anglian Water: £62.8m.")
    pack = load("osint")
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, archive=arc)
    w.step()
    prime = next(iter(w.communities))
    cap = sorted(w.communities[prime].capabilities)[0]
    job = MarketJob("T1", "q", 1, {cap: Part(cap, "s", "r")}, posted=w.cycle, deadline=w.cycle + 9, prime=prime)
    job.status = "claimed"
    w.jobs[job.id] = job
    bad = "x [archive: web-www-ofwat-gov-uk-wp-content-uploads-2025-10-wcpr-2025-pdf#1]"
    out = Actions(w, w.communities[prime]).do_part(job.id, cap, bad)
    assert not out and "did you mean web-www-ofwat-gov-uk-wp-content-uploads-2025-10-wcpr-24-25-pdf#1?" in out.message


@pytest.mark.parametrize("title,generic", [("PowerPoint Presentation", True), ("Microsoft Word - draft3.docx", True),
                                           ("", True), ("WCPR-24-25.pdf", True),
                                           ("Water company performance report 2024-25", False)])
def test_titles_that_say_nothing_are_recognised(title, generic):
    from commons.adapters.web import _generic
    assert _generic(title) is generic


def test_a_report_title_drops_the_questions_kind_tag(tmp_path):
    pack = load("osint")
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, answers=tmp_path)
    w.step()
    job = MarketJob("J3", "[org] What has Ofwat fined?", 1, {"report": Part("report", "s", "r", artifact="A", source="self")},
                    posted=0, deadline=9, prime=next(iter(w.communities)))
    text = w.answers.write(job, paid=False, why="x").read_text()
    assert text.startswith("# J3 · What has Ofwat fined?") and "[org]" not in (tmp_path / "README.md").read_text()


def test_when_the_model_backend_fails_for_every_co_op_the_society_halts():
    """12 Oct: LM Studio's engine stalled and the run went on for two cycles with no model."""
    def down(system, messages, tools):
        raise ModelError("LM Studio returned 400: Engine protocol predict stream timed out")
    pop = [Community(f"c{i}", 2, {"build"}, LLMStrategy(FakeBackend(converse=down))) for i in range(2)]
    w = World(Params(seed=0, verify=False), population=pop)
    try:
        w.step()
    except Exception:
        pass
    assert w.meter.halted
    assert any("model backend failed for every co-op" in e.text for e in w.activity.recent(20))


def test_an_ungrounded_figure_is_refused_at_hand_in_with_the_reason():
    from commons.domain.archive import ArchiveIndex
    arc = ArchiveIndex()
    pid = arc.add_page("https://www.clientearth.org/ruling", "Ruling", "The judge agreed emissions should count.")[0]
    pack = load("osint")
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, archive=arc)
    w.step()
    prime = next(iter(w.communities))
    cap = sorted(w.communities[prime].capabilities)[0]
    job = MarketJob("T1", "q", 1, {cap: Part(cap, "s", "r")}, posted=w.cycle, deadline=w.cycle + 9, prime=prime)
    job.status = "claimed"
    w.jobs[job.id] = job
    out = Actions(w, w.communities[prime]).do_part(job.id, cap, f"In January 2025 the judge ruled [archive: {pid}].")
    assert not out and '"January 2025"' in out.message and pid in out.message and "take it out" in out.message


def test_with_bids_in_an_announcement_is_awarded_early():
    """12 Oct: jobs missed deadlines waiting out bid windows; OSINT's live settings award after two cycles."""
    from tests.application.test_turns_and_contracts import act, claimed_job_needing_build, world
    w = world(auto_award_after=2, bid_window=6)
    job = claimed_job_needing_build(w)
    job.deadline = w.cycle + 20
    cid = act(w, "prime").announce(job.id, "build", 30_000, 0.5).id
    assert act(w, "sub").bid(cid, 20_000)
    w.step()
    assert w.contracts[cid].status == "open"  # one cycle: others may still bid
    w.step()
    assert w.contracts[cid].status == "awarded" and w.cycle < w.contracts[cid].deadline


def test_a_co_op_can_be_held_to_one_job_at_a_time():
    from tests.application.test_turns_and_contracts import act, world
    w = world(max_held_jobs=1)
    for n in range(2):
        w.jobs[f"H{n}"] = MarketJob(f"H{n}", "kit", 80_000, {"research": Part("research", "r", "r")}, posted=w.cycle,
                                    deadline=w.cycle + 5)
    act(w, "prime").me.capacity = 10
    assert act(w, "prime").claim("H0")
    assert "finish one first" in act(w, "prime").claim("H1").message
    assert load("osint").live_params["max_held_jobs"] == 1 and load("osint").live_params["job_ttl"] == 18
