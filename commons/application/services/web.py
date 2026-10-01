"""The web, behind the gate: every read an agent asks for goes to the gate (commons/application/gate.py), which allows
it, queues it for the operator, or refuses it. Network calls run without the world's lock; the lock is taken only to
ask the gate and to record results. Pages read join the archive, so citing them is checked like any citation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.observation import (
    Outcome,
)
from commons.application.ports import WebError, host_of
from commons.domain.gate import Request as GateRequest
from commons.domain.status import (
    RequestStatus,
)

if TYPE_CHECKING:
    from commons.application.world import World


class WebDesk:
    def __init__(self, world: World):
        self.w = world
        self.web_pages = {}  # url -> archive passage ids, for pages read this run

    def begin_cycle(self) -> None:
        """A new cycle for the gate: fresh web budgets, your decisions from file, expired requests. Under the lock."""
        self.w.gate.begin_cycle()
        for r in self.w.gate.reload():
            self.decided(r)
        for r in self.w.gate.expire(self.w.cycle):
            self.w.tell(r.coop, "gate", f"{r.id} ({r.tool} {r.target[:80]}) expired without a decision", r.id)
            self.w.hub.emit("gate.decision", self.w.cycle, id=r.id, coop=r.coop, status=r.status)

    def decide(self, ids, approve: bool, always: bool = False, reason: str = "") -> list[GateRequest]:
        """Your decisions, from the dashboard. Approved requests run at the start of the next cycle."""
        with self.w.lock:
            done = self.w.gate.decide(ids, approve, always, reason)
            for r in done:
                self.decided(r)
            return done

    def decided(self, r: GateRequest) -> None:
        what = f"{r.tool} {r.target[:80]}"
        if r.status == RequestStatus.DENIED:
            self.w.tell(r.coop, "gate", f"the operator denied {r.id} ({what})" + (f": {r.reason}" if r.reason else ""), r.id)
        else:
            self.w.tell(r.coop, "gate", f"the operator approved {r.id} ({what}); it runs at the start of next cycle"
                       + (f", and your reads from {r.host} no longer need approval" if r.always else ""), r.id)
        self.w.activity.add(self.w.cycle, r.coop, "operator", "change", "gate", f"{r.status} {r.id}: {what}", r.status == RequestStatus.APPROVED,
                          {"id": r.id, "always": r.always})
        self.w.hub.emit("gate.decision", self.w.cycle, id=r.id, coop=r.coop, status=r.status, always=r.always)

    def call(self, coop: str, actor: str, tool: str, target: str):
        """A web read an agent asked for. Called WITHOUT the world's lock: the network is slow, so the lock is taken
        only to ask the gate and to record the result."""
        target = str(target).strip()[:500]
        if not self.w.web or not self.w.gate.policy.allow_hosts:
            return Outcome(False, "this society has no web access (the operator allows no hosts)")
        if tool == "web_fetch":
            with self.w.lock:
                if target in self.web_pages:
                    ids = self.web_pages[target]
                    return Outcome(True, f"already read: {target} is archive passages {', '.join(ids)}; use read_archive",
                                   ids[0] if ids else None)
            host = host_of(target)
        else:
            if self.w.web.search_host is None or self.w.gate.policy.search == "none":
                return Outcome(False, "this society has no web search; web_fetch a page on an allowed host instead")
            host = self.w.web.search_host
        with self.w.lock:
            verdict, r = self.w.gate.ask(coop, actor, tool, target, host, self.w.cycle)
            if isinstance(r, GateRequest):
                self.w.hub.emit("gate.request", self.w.cycle, id=r.id, coop=coop, tool=tool, target=target, host=host,
                              status=r.status)
        if verdict == "deny":
            return Outcome(False, f"the gate refused: {r}")
        if verdict == "pending":
            return Outcome(False, f"waiting for the operator's approval as {r.id}. If approved it runs at the start of a "
                                  f"later cycle and you'll be told the result; don't ask again.", r.id)
        return self.execute(r)

    def run_approved(self) -> None:
        """Requests you approved since last cycle: run them (outside the lock) and tell whoever asked."""
        with self.w.lock:
            todo = self.w.gate.approved()
        for r in todo:
            out = self.execute(r)
            with self.w.lock:
                self.w.tell(r.coop, "gate", f"{r.id} ran: {out.message[:700]}", r.id)

    def execute(self, r: GateRequest):
        try:
            if r.tool == "web_search":
                results = self.w.web.search(r.target, k=5)
                text = "\n".join(f"- {x.title}: {x.url}\n  {x.snippet[:200]}" for x in results) or "no results"
                msg, ref = f"search results for {r.target!r} (web_fetch a url to read it):\n{text}", None
            else:
                page = self.w.web.fetch(r.target)
                with self.w.lock:
                    ids = self.w.archive.add_page(page.url, page.title, page.text, fetched=f"cycle {self.w.cycle}")
                    self.web_pages[r.target] = self.web_pages[page.url] = ids
                first = self.w.archive.get(ids[0]).text if ids else ""
                msg, ref = (f"read {page.url} ({page.title[:80]}) into the archive as {len(ids)} passage(s): "
                            f"{', '.join(ids[:12])}{' …' if len(ids) > 12 else ''}. Cite them as [archive: <id>]. The "
                            f"first:\n<untrusted>\n{first[:1500]}\n</untrusted>"), (ids[0] if ids else None)
            ok = True
        except WebError as e:
            msg, ref, ok = f"{r.tool} failed: {e}", None, False
        with self.w.lock:
            r.status, r.result = (RequestStatus.DONE if ok else RequestStatus.FAILED), msg[:300]
            self.w.hub.emit("web.call", self.w.cycle, id=r.id, coop=r.coop, tool=r.tool, target=r.target, ok=ok)
        return Outcome(ok, msg, ref)
