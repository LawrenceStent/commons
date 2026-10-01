"""R4.3: the job aggregate. Posted, claimed, graded, then paid or failed; its value scales with quality."""

import pytest

from commons.domain.errors import DomainError
from commons.domain.market import TRANSITIONS, MarketJob, Part
from commons.domain.status import JobStatus as S


def job(caps=("research", "write"), reward=80_000) -> MarketJob:
    return MarketJob("J1", "kit", reward, {c: Part(c, f"do {c}", "rubric") for c in caps}, posted=1, deadline=4)


def claimed() -> MarketJob:
    j = job()
    j.claim("studio", deadline=12, bond=8_000)
    return j


def test_a_posted_job_is_claimed_once():
    j = job()
    j.claim("studio", deadline=12, bond=8_000)
    assert (j.status, j.prime, j.deadline, j.bond) == (S.CLAIMED, "studio", 12, 8_000)
    with pytest.raises(DomainError, match="can't"):
        j.claim("lab", deadline=12)


def test_parts_fill_until_the_job_is_complete():
    j = claimed()
    j.fill("research", "notes", source="self", cites=("pb1",))
    assert not j.complete and j.parts["research"].cites == ("pb1",)
    with pytest.raises(DomainError, match="already done"):
        j.fill("research", "again", source="self")
    j.fill("write", "copy", source="J1.write.1")
    assert j.complete
    with pytest.raises(DomainError, match="no design part"):
        j.fill("design", "x", source="self")


def test_parts_can_only_be_filled_while_claimed():
    with pytest.raises(DomainError):
        job().fill("research", "notes", source="self")


def test_value_scales_with_quality_and_passing_needs_every_part():
    j = claimed()
    j.record_score("research", 1.0)
    j.record_score("write", 0.5)
    assert j.mean_score == 0.75 and j.value(quality_pay=0.5) == round(80_000 * (0.5 + 0.5 * 0.75))
    assert j.passed(0.5) and not j.passed(0.6)
    assert j.value(quality_pay=0.0) == 80_000


def test_paid_straight_away_or_after_waiting():
    j = claimed()
    j.pay()
    assert j.status == S.PAID
    k = claimed()
    k.defer(until=20)
    assert (k.status, k.settle_at) == (S.GRADED, 20)
    k.await_grants()  # a deferred job that passes waits for this cycle's grants
    k.pay()
    assert k.status == S.PAID


def test_fail_from_claimed_or_graded_and_the_bond_is_released_once():
    j = claimed()
    j.await_grants()
    j.fail()
    assert j.status == S.FAILED
    assert j.release_bond() == 8_000 and j.release_bond() == 0


def test_only_posted_jobs_expire():
    j = job()
    j.expire()
    assert j.status == S.EXPIRED
    with pytest.raises(DomainError):
        claimed().expire()


def test_closed_jobs_stay_closed():
    j = claimed()
    j.pay()
    for move in (j.fail, j.pay, j.await_grants, j.expire):
        with pytest.raises(DomainError):
            move()
    with pytest.raises(DomainError):
        j.defer(until=30)


def test_the_table_names_every_status():
    assert set(TRANSITIONS) == set(S)
    assert {s for s, nxt in TRANSITIONS.items() if not nxt} == {S.PAID, S.FAILED, S.EXPIRED}
