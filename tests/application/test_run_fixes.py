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
