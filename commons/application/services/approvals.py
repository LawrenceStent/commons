"""Requests the gate holds for you, other than web reads: asking (a pack's desk publishing something, a co-op
changing its charter) and carrying out what you approved. Approved requests run at the start of the next cycle, each
by whoever owns it: web reads by the web desk, charter changes by the population rules, anything else by the pack's
desk (its `carry_out`). The co-op that asked is told the result."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.domain import events as ev
from commons.domain.gate import TOOLS as WEB_TOOLS
from commons.domain.gate import Request as GateRequest
from commons.domain.status import RequestStatus

if TYPE_CHECKING:
    from commons.application.society import World

CARRIERS: dict = {}  # tool -> fn(world, request) -> (ok, message), for kernel requests (charters register here)


class Approvals:
    def __init__(self, world: World):
        self.w = world

    def request(self, coop: str, actor: str, tool: str, risk: str, target: str, detail: str) -> Outcome:
        """Ask the gate. Under the lock. The answer says it's waiting for you (and as what), or why it's refused."""
        verdict, r = self.w.gate.propose(coop, actor, tool, risk, target, detail, self.w.cycle)
        if verdict == "deny" or not isinstance(r, GateRequest):
            return Outcome(False, f"the gate refused: {r}")
        if r.cycle == self.w.cycle and r.status == RequestStatus.PENDING:
            self.w.events.publish(ev.GateRequested(r))
        return Outcome(True, f"waiting for the operator's approval as {r.id}; you'll be told when it's decided", r.id)

    def run(self) -> None:
        """Everything you approved since last cycle, outside the lock (a channel or the web may be slow)."""
        with self.w.lock:
            todo = self.w.gate.approved()
        for r in todo:
            if r.tool in WEB_TOOLS:
                out = self.w.web_desk.execute(r)
                with self.w.lock:
                    self.w.events.publish(ev.QueuedReadRan(r, out.message))
                continue
            ok, message = self._carry_out(r)
            with self.w.lock:
                r.status, r.result = (RequestStatus.DONE if ok else RequestStatus.FAILED), message[:300]
                self.w.events.publish(ev.QueuedReadRan(r, message))

    def _carry_out(self, r: GateRequest) -> tuple[bool, str]:
        if carry := CARRIERS.get(r.tool):
            return carry(self.w, r)
        if self.w.desk is not None and (carry := getattr(self.w.desk, "carry_out", None)):
            return carry(self.w, r)
        return False, f"nothing here can carry out {r.tool}"
