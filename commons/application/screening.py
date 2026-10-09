"""The pack's screen, applied during a run (commons/domain/pack.py `screen`): a web request before the gate sees it,
work at hand-in. A refusal is a screened attempt: published as an event (the co-op is told, telemetry records it),
and if the pack says so the society halts until you reset it. Founding applies the same screen to briefs and
questions (commons/application/founding.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import hashlib

from commons.application.observation import Outcome
from commons.application.services.approvals import CARRIERS
from commons.domain import events as ev
from commons.domain.pack import screened
from commons.domain.status import RequestStatus

if TYPE_CHECKING:
    from commons.application.society import World


def screen(w: World, coop: str, kind: str, text: str) -> str | None:
    """Why the attempt is refused (and recorded), or None. Call it under the world's lock."""
    why = screened(w.pack, kind, text)
    if why is None:
        return None
    halt = w.pack.halt_on_screen
    w.events.publish(ev.Screened(coop, kind, text[:200], why, halt))
    if halt:
        w.meter.halt(f"screened attempt by {coop}: {why}", w.cycle)
    return f"refused by this society's screen: {why}" + (" (the society is halted)" if halt else "")


REVIEW = "review_work"  # the gate tool for work held for your editorial decision


def work_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def review_work(w: World, coop: str, actor: str, text: str) -> Outcome | None:
    """Handed-in work the screen flags (your decision, 9 Oct: two false alarms halted live runs). With the pack's
    `review_flagged_work` and the operator's [gate] publish = "ask", it waits for your editorial decision instead of
    halting: approve it and the co-op hands in the same text again, which then passes; deny it and the co-op rewrites.
    Otherwise (no review, or publish not "ask") the screen refuses it as before, halting if the pack says so. Call it
    under the world's lock."""
    why = screened(w.pack, "work", text)
    if why is None:
        return None
    key = work_key(text)
    if any(r.tool == REVIEW and r.target == key and r.status in (RequestStatus.APPROVED, RequestStatus.DONE)
           for r in w.gate.requests.values()):
        return None  # you read it and let it through
    if w.pack.review_flagged_work and w.gate.policy.publish == "ask":
        out = w.approvals.request(coop, actor, REVIEW, "publish", key,
                                  f"Flagged by the screen: {why}\nApprove to let it into the record; deny and the "
                                  f"co-op rewrites it.\n\n{text[:3500]}")
        if out.ok:
            return Outcome(False, f"held for the operator's editorial review ({out.id}): the screen flagged it ({why}). "
                                  "Carry on with other work. If it's approved you'll be told: hand in exactly the same "
                                  "text again and it will pass; if it's denied, rewrite it without what was flagged.")
    return Outcome(False, screen(w, coop, "work", text) or why)


def _approve_work(w: World, r) -> tuple[bool, str]:
    return True, "approved: hand in the same text again and it will pass the screen"


CARRIERS[REVIEW] = _approve_work
