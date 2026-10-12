"""Grounding (12 Oct): every figure and date in a cited claim must be in the passage it cites. The three answers the
first long OSINT runs failed at grading, as cases."""

import pytest

from commons.domain.grounding import facts, ungrounded

P = {
    "bbc#3": "In January 2025, a court ruled that the approval for two Scottish oil and gas fields was unlawful.",
    "ce#3": "The judge Lord Ericht agreed climate impact from burning the fuels should have been considered.",
    "of#45": "In May 2025 a financial penalty of £104.5m was imposed on Thames Water.",
    "ccc#1": "Emissions fell to 413.7 MtCO2e in 2024, 2.5 per cent lower than 2023-24 levels.",
    "tb#1": "The Thames Barrier has closed 221 times since 1982.",
}


@pytest.mark.parametrize("text,bad", [
    ("In January 2025, Lord Ericht ruled the consent unlawful [archive: ce#3].", ["January 2025"]),  # J1
    ("Spill counts rose from 5.9 to 7.7 per site [archive: tb#1].", ["5.9", "7.7"]),  # J7
    ("Thames Water was fined £120 million in May 2025 [archive: of#45].", ["£120 million"]),
])
def test_a_figure_or_date_not_in_its_cited_passage_is_found(text, bad):
    assert [u.fact for u in ungrounded(text, P)] == bad


@pytest.mark.parametrize("text", [
    "In January 2025, Lord Ericht ruled the consent unlawful [archive: ce#3][archive: bbc#3].",  # J1, fixed
    "In May 2025 Ofwat fined Thames Water £104,500,000 [archive: of#45].",  # scale-aware: £104.5m
    "UK emissions fell 2.5% to 413.7 MtCO2e in 2024 [archive: ccc#1].",  # % and per cent
    "1. The barrier closed 221 times, three times last year [archive: tb#1].",  # list markers, small counts
    "Claim 2: closures since 1982 are supported [archive: tb#1].",
    "Unsourced figures like 999 aren't this rule's business.",  # no citation: the grader judges it
])
def test_grounded_claims_pass(text):
    assert ungrounded(text, P) == []


def test_facts_are_scale_aware_and_typed():
    kinds = {(f.kind, f.value) for f in facts("£1.2m, 3 million people, 45%, 30 January 2025, in 2023/24, 413.7")}
    assert ("money", 1_200_000) in kinds and ("money", 3_000_000) in kinds and ("month", "2025-01") in kinds
    assert ("year", 2023) in kinds and ("year", 2024) in kinds and any(k == "percent" for k, _ in kinds)
