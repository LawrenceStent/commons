"""Verification decides payment: a checker's tally (`Supported: N of M. Contradicted: K.`) is read by rule."""

from commons.domain.format import Format
from commons.domain.market import MarketJob, Part
from commons.domain.verification import Tally, read_tally, verdict


def test_the_last_tally_in_the_work_is_read_and_an_impossible_one_is_not():
    assert read_tally("Supported: 1 of 2. Contradicted: 1.\n...\nSupported: 4 of 5. Contradicted: 0.") == Tally(4, 5, 0)
    assert read_tally("supported: 3/3 contradicted: 0") == Tally(3, 3, 0)
    assert read_tally("Supported: 4 of 3. Contradicted: 0.") is None
    assert read_tally("all fine") is None and read_tally(None) is None


def test_a_contradicted_claim_or_too_few_supported_fails_the_job():
    assert "1 claim(s) contradicted" in verdict(Tally(4, 5, 1), 0.5)
    assert "only 2 of 5" in verdict(Tally(2, 5, 0), 0.5)
    assert verdict(Tally(3, 5, 0), 0.5) is None and verdict(Tally(0, 0, 0), 0.5) is None


def test_a_format_can_require_the_tally():
    f = Format(tally=True)
    assert "closing tally line" in f.describe()
    assert f.problems("looks fine to me") and not f.problems("Supported: 2 of 2. Contradicted: 0.")


def test_only_an_independent_part_s_tally_counts_and_pay_scales_with_it():
    job = MarketJob("J1", "q", 100_000, {"report": Part("report", "r", "r"),
                                         "verify": Part("verify", "v", "v", independent=True)}, posted=0, deadline=9)
    job.parts["report"].artifact = "Supported: 0 of 9. Contradicted: 9."  # an author's own count isn't a check
    assert job.tally() is None
    job.parts["verify"].artifact = "Checked.\nSupported: 3 of 4. Contradicted: 0."
    assert job.tally() == Tally(3, 4, 0)
    job.scores = {"report": 1.0, "verify": 1.0}
    assert job.value(0.5) == 100_000
    job.verified = 0.75
    assert job.value(0.5) == 75_000


def test_a_format_can_require_distinct_sources_and_one_page_is_one_source():
    f = Format(min_sources=2)
    assert "at least 2 different sources" in f.describe()
    one = "[archive: suez#1] and [archive: suez#2] and [archive: Suez#3]"
    assert "cites 1 different source(s)" in f.problems(one)[0]
    assert not f.problems(one + " [archive: lloyds-list#4]")
