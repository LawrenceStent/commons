"""R4.1: the Contract aggregate. Its lifecycle is a table; every move is a method; an illegal move raises."""

import pytest

from commons.domain.contract import TRANSITIONS, Contract
from commons.domain.errors import DomainError
from commons.domain.status import ContractStatus as S


def contract(**kw) -> Contract:
    base = dict(id="J1.write.1", job_id="J1", capability="write", prime="studio", spec="s", rubric="r",
                max_price=100, advance_frac=0.5, announced=3, deadline=6)
    return Contract(**{**base, **kw})


def delivered() -> Contract:
    c = contract()
    c.bid("lab", 80)
    c.award("lab", 80, 40, deliver_by=9)
    c.deliver("the work", ("pb1",), review_by=11)
    return c


def test_a_new_contract_is_open_and_takes_bids():
    c = contract()
    assert c.status == S.OPEN and c.live and c.closed is None
    c.bid("lab", 80)
    c.bid("lab", 70)  # a later bid replaces an earlier one
    assert c.bids == {"lab": 70}


def test_award_deliver_accept():
    c = contract()
    c.bid("lab", 80)
    c.award("lab", 80, 40, deliver_by=9)
    assert (c.status, c.winner, c.price, c.advance, c.deadline, c.owed) == (S.AWARDED, "lab", 80, 40, 9, 40)
    c.deliver("the work", ("pb1",), review_by=11)
    assert (c.status, c.artifact, c.cites, c.deadline) == (S.DELIVERED, "the work", ("pb1",), 11)
    c.accept("good", at=10)
    assert (c.status, c.reason, c.closed, c.live) == (S.ACCEPTED, "good", 10, False)


def test_a_rejection_can_be_disputed_once_and_overturned():
    c = delivered()
    c.reject("weak", at=10)
    assert (c.status, c.closed) == (S.REJECTED, 10)
    c.file_dispute()
    with pytest.raises(DomainError, match="already"):
        c.file_dispute()
    c.overturn("overturned on audit", at=12)
    assert (c.status, c.reason, c.closed) == (S.ACCEPTED, "overturned on audit", 12)


def test_a_dropped_dispute_may_be_filed_again():
    c = delivered()
    c.reject("weak", at=10)
    c.file_dispute()
    c.drop_dispute()
    c.file_dispute()
    assert c.disputed


@pytest.mark.parametrize("move, start", [
    ("expire", S.OPEN), ("withdraw", S.OPEN), ("fail", S.AWARDED), ("default", S.DELIVERED), ("default", S.REJECTED),
])
def test_closing_moves(move, start):
    c = {S.OPEN: contract, S.AWARDED: lambda: _awarded(), S.DELIVERED: delivered, S.REJECTED: _rejected}[start]()
    getattr(c, move)(at=20)
    assert c.closed == 20 and not c.live


def _awarded():
    c = contract()
    c.award("lab", 80, 40, deliver_by=9)
    return c


def _rejected():
    c = delivered()
    c.reject("weak", at=10)
    return c


@pytest.mark.parametrize("move, args", [
    ("award", ("lab", 80, 40)), ("deliver", ("x", ())), ("accept", ("ok",)), ("reject", ("no",)), ("fail", ()),
    ("default", ()), ("overturn", ("x",)), ("withdraw", ()), ("expire", ()),
])
def test_every_move_is_refused_from_a_closed_contract(move, args):
    c = delivered()
    c.accept("good", at=10)
    kw = {"deliver_by": 1} if move == "award" else {"review_by": 1} if move == "deliver" else {"at": 1}
    with pytest.raises(DomainError, match="can't"):
        getattr(c, move)(*args, **kw)


def test_bids_only_while_open_and_disputes_only_after_a_rejection():
    c = _awarded()
    with pytest.raises(DomainError):
        c.bid("other", 50)
    with pytest.raises(DomainError):
        c.file_dispute()


def test_the_table_names_every_status_and_only_rejected_reopens():
    assert set(TRANSITIONS) == set(S)
    terminal = {s for s, nxt in TRANSITIONS.items() if not nxt}
    assert terminal == {S.ACCEPTED, S.FAILED, S.DEFAULTED, S.EXPIRED, S.WITHDRAWN}
    assert TRANSITIONS[S.REJECTED] == {S.ACCEPTED, S.DEFAULTED}


def test_a_withdrawal_without_a_cycle_leaves_it_unclosed():
    """Today the executor withdraws an open contract without closing it (see REFACTOR-PLAN §7); the aggregate keeps
    that behaviour explicit rather than hiding it."""
    c = contract()
    c.withdraw(at=None)
    assert c.status == S.WITHDRAWN and c.closed is None
