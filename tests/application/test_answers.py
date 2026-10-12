"""Finished jobs written out as reports, Markdown and PDF (your decision, 11 Oct), failed ones too, marked."""

from commons.application.services.answers import folder_for
from commons.application.society import Params, World
from commons.domain.archive import ArchiveIndex
from commons.domain.grading import Grade
from commons.domain.market import MarketJob, Part
from commons.domain.pack import load


def test_a_live_run_writes_its_answers_beside_its_runs_folder():
    assert str(folder_for("societies/uk-climate/runs/live-x.sqlite")) == "societies/uk-climate/answers/live-x"
    assert str(folder_for("runs/ticks/paper/state/ledger.sqlite")) == "runs/ticks/paper/answers"  # one continuous run
    assert folder_for(":memory:") is None


def test_every_finished_job_gets_a_markdown_and_pdf_report_and_an_index(tmp_path):
    pack = load("osint")
    w = World(Params(**{**pack.params, "seed": 0}), pack=pack, answers=tmp_path / "answers")
    w.run(60)
    md = sorted((tmp_path / "answers").glob("J*.md"))
    assert md and len(md) == len(list((tmp_path / "answers").glob("J*.pdf")))
    index = (tmp_path / "answers" / "README.md").read_text()
    assert "paid" in index and md[0].name in index
    assert (tmp_path / "answers" / md[0].name.replace(".md", ".pdf")).read_bytes()[:5] == b"%PDF-"


def test_a_failed_job_is_written_marked_not_verified_with_its_sources_and_the_graders_reasons(tmp_path):
    pack = load("osint")
    arc = ArchiveIndex()
    arc.add_page("https://www.ofwat.gov.uk/report.pdf", "Water company performance report 2024-25",
                 "Ofwat fined Thames Water £104.5m for wastewater failures.\n\nDŵr Cymru misreported leakage.")
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, archive=arc, answers=tmp_path)
    w.step()
    job = MarketJob("J3", "What has Ofwat found and fined since 2023?", 400_000,
                    {"analyse": Part("analyse", "s", "r", artifact="Findings\nThames Water was fined "
                                     "[archive: web-www-ofwat-gov-uk-report-pdf#1].", source="self"),
                     "report": Part("report", "s", "r", artifact="Answer\nSouth West Water was fined "
                                    "[archive: web-www-ofwat-gov-uk-report-pdf#2].", source="self")},
                    posted=0, deadline=9, prime=next(iter(w.communities)))
    w.answers.reasons["J3"] = {"report": (0.2, "cites a source that doesn't mention South West Water")}
    path = w.answers.write(job, paid=False, why="a part failed grading (report 0.20)")
    text = path.read_text()
    assert text.index("## Answer") < text.index("## Analysis")  # the pack's reading order
    assert "NOT VERIFIED · failed: a part failed grading" in text
    assert "South West Water was fined [1]." in text and "[archive:" not in text
    assert "1. [Water company performance report 2024-25](https://www.ofwat.gov.uk/report.pdf) (passages #1, #2)" in text
    assert "| report | 0.20 | cites a source that doesn't mention South West Water |" in text
    assert path.with_suffix(".pdf").read_bytes()[:5] == b"%PDF-"


def test_typst_markup_in_a_models_words_stays_text(tmp_path):
    """The words are data, never markup: a model can't run Typst code through its answer."""
    from commons.application.services.answers import pdf
    report = {"id": "J1", "title": '#eval("1")', "status": "Paid", "status_short": "paid", "prime": "a", "cycle": 1,
              "parts": [{"capability": "report", "heading": "Answer", "text": '#read("/etc/passwd") $x$ *bold*',
                         "by": "a", "how": "its own work", "grade": (0.9, "#panic()")}], "sources": []}
    assert pdf(report)[:5] == b"%PDF-"


def test_a_part_accepted_without_grading_is_marked_in_the_report(tmp_path):
    from commons.domain.contract import Contract
    pack = load("osint")
    w = World(Params(**{**pack.params, "seed": 0, "verify": False}), pack=pack, answers=tmp_path)
    w.step()
    prime, sub = list(w.communities)[:2]
    c = Contract("J9.verify.1", "J9", "verify", prime, "s", "r", 100_000, 0.5, announced=0, deadline=4)
    c.bid(sub, 90_000)
    c.award(sub, 90_000, 45_000, deliver_by=9)
    c.deliver("Supported: 1 of 1. Contradicted: 0.", (), review_by=9)
    c.accept("accepted by default: the grader was unavailable", at=1)
    w.contracts[c.id] = c
    job = MarketJob("J9", "Q?", 1, {"verify": Part("verify", "s", "r", artifact=c.work, source=c.id, independent=True)},
                    posted=0, deadline=9, prime=prime)
    text = w.answers.write(job, paid=True, why="").read_text()
    assert "NOT GRADED: accepted by default: the grader was unavailable" in text
