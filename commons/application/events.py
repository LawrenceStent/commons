"""Publishing domain events (commons/domain/events.py) and what follows from them.

    notices    what co-ops are told (their inbox, read at their next turn)
    telemetry  what the telemetry hub records (and, through it, the activity log and the dashboard)

Each is a function per event type (functools.singledispatch); an event no function knows is a programming error.
Notices are delivered before telemetry is emitted; each stream keeps the order events were published in.
"""

from __future__ import annotations

from functools import singledispatch
from typing import TYPE_CHECKING

from commons.domain import events as ev

if TYPE_CHECKING:
    from commons.application.society import World


class Events:
    def __init__(self, world: World):
        self.w = world

    def publish(self, event: ev.Event) -> None:
        for to, kind, text, ref in notices(event, self.w):
            self.w.tell(to, kind, text, ref)
        for kind, fields in telemetry(event, self.w):
            self.w.hub.emit(kind, self.w.cycle, **fields)


# ── what co-ops are told ───────────────────────────────────────
@singledispatch
def notices(event: ev.Event, w: World) -> list[tuple[str, str, str, str | None]]:
    raise TypeError(f"no notices defined for {type(event).__name__}")


@singledispatch
def telemetry(event: ev.Event, w: World) -> list[tuple[str, dict]]:
    raise TypeError(f"no telemetry defined for {type(event).__name__}")


def _stage(c, stage, **extra) -> tuple[str, dict]:
    return "contract.stage", dict(id=c.id, capability=c.capability, prime=c.prime, winner=c.winner, stage=stage,
                                  price=c.price, max_price=c.max_price, bids=dict(c.bids), **extra)


@notices.register
def _(e: ev.ContractOpened, w):
    return []


@telemetry.register
def _(e: ev.ContractOpened, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractAwarded, w):
    c = e.contract
    return [(c.winner, "awarded", f"you won {c.id} at {c.price}; advance {c.advance} paid; deliver by cycle {c.deadline}",
             c.id)] + [(loser, "bid_lost", f"{c.id} went to another bidder", c.id) for loser in e.losers]


@telemetry.register
def _(e: ev.ContractAwarded, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractDelivered, w):
    c = e.contract
    when = "the grader judges it at the end of this cycle" if e.judged_by_grader else f"review by cycle {c.deadline}"
    return [(c.prime, "delivered", f"{c.winner} delivered {c.id}; {when}", c.id)]


@telemetry.register
def _(e: ev.ContractDelivered, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractExpired, w):
    return [(e.contract.prime, "expired", f"{e.contract.id} closed with no award", e.contract.id)]


@telemetry.register
def _(e: ev.ContractExpired, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractFailed, w):
    c = e.contract
    return [(c.prime, "failed", f"{c.winner} never delivered {c.id}", c.id),
            (c.winner, "failed", f"you missed the delivery deadline on {c.id}", c.id)]


@telemetry.register
def _(e: ev.ContractFailed, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractWithdrawn, w):
    return []


@telemetry.register
def _(e: ev.ContractWithdrawn, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractReviewed, w):
    c = e.contract
    if e.accepted:
        return [(c.winner, "accepted", f"{c.prime} accepted {c.id} and paid {c.owed}", c.id)]
    return [(c.winner, "rejected", f"{c.prime} rejected {c.id}: {e.reason or 'no reason given'}", c.id)]


@telemetry.register
def _(e: ev.ContractReviewed, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractDefaulted, w):
    c = e.contract
    return [(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)]


@telemetry.register
def _(e: ev.ContractDefaulted, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.AuditFiled, w):
    c = e.contract
    return [(c.prime, "audit_filed", f"{c.winner} disputed your rejection of {c.id}; the grader decides this cycle", c.id)]


@telemetry.register
def _(e: ev.AuditFiled, w):
    return [_stage(e.contract, "audit_filed")]


@notices.register
def _(e: ev.AuditUpheld, w):
    c, s = e.contract, e.score
    return [(c.prime, "audit", f"the audit upheld your rejection of {c.id} ({s:.2f})", c.id),
            (c.winner, "audit", f"the audit upheld the rejection of {c.id}: your delivery scored {s:.2f}; the fee is gone",
             c.id)]


@telemetry.register
def _(e: ev.AuditUpheld, w):
    return [_stage(e.contract, "audit_upheld", score=e.score)]


@notices.register
def _(e: ev.AuditOverturned, w):
    c = e.contract
    return [(c.prime, "audit", f"the audit overturned your rejection of {c.id}; you paid {e.owed} plus the {e.fee} fee",
             c.id),
            (c.winner, "audit", f"the audit found for you on {c.id} ({e.score:.2f}): {c.prime} paid {e.owed} plus your "
                                f"{e.fee} fee", c.id)]


@telemetry.register
def _(e: ev.AuditOverturned, w):
    return [_stage(e.contract, e.contract.status), _stage(e.contract, "audit_overturned", score=e.score)]


@notices.register
def _(e: ev.AuditUnpaid, w):
    c = e.contract
    return [(c.winner, "audit", f"the audit found for you on {c.id}, but {c.prime} can't pay", c.id)]


@telemetry.register
def _(e: ev.AuditUnpaid, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.AuditCancelled, w):
    c = e.contract
    return [(c.winner, "audit", f"the grader was unavailable for the audit of {c.id}; your fee was refunded", c.id)]


@telemetry.register
def _(e: ev.AuditCancelled, w):
    return []
