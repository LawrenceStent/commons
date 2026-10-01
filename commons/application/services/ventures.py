"""Ventures: work co-ops propose for themselves, appraised at the start of the next cycle (outside the world's lock),
priced by a fixed formula and approved by score, never by who asked first, up to `venture_budget` a cycle. The rules
are in commons/domain/ventures.py and commons/application/ventures.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.market import MarketJob, Part
from commons.domain.status import (
    VentureStatus,
)
from commons.domain.ventures import AppraisalError, Venture
from commons.domain.ventures import value as venture_value
from commons.substrate.ledger import purse

if TYPE_CHECKING:
    from commons.application.society import World


class VentureDesk:
    def __init__(self, world: World):
        self.w = world

    def appraise(self) -> None:
        """Appraise waiting ventures outside the lock (a model call must never stall other communities),
        then decide under it: best score first, up to the market's budget for this cycle."""
        with self.w.lock:
            todo = [v for v in self.w.ventures.values() if v.status == VentureStatus.PENDING and v.score is None]
        results = self._appraisals(todo)
        with self.w.lock:
            for vid, a in results.items():
                self._price(self.w.ventures[vid], a)
            self._approve_best()

    def _appraisals(self, todo: list[Venture]) -> dict:
        def appraise(v):
            try:
                return v, self.w.appraiser.appraise(v)
            except AppraisalError as e:
                return v, e

        results = {}
        for v, a in self.w.grading.map_calls(appraise, todo):
            if isinstance(a, AppraisalError):
                with self.w.lock:
                    self.w.events.publish(ev.VentureDelayed(v, str(a)))
            else:
                results[v.id] = a
        return results

    def _price(self, v: Venture, a) -> None:
        """Score and price a venture, pay for its appraisal, and refuse it at once if it's worth nothing."""
        p = self.w.params
        v.score, v.reason, v.reward = a.score, a.reason, venture_value(a.score, p.market.job_reward, p.ventures.venture_min_score)
        if a.cost:
            payer = "treasury" if self.w.ledger.balance("treasury") >= a.cost else purse(v.proposer)
            self.w.ledger.transfer(payer, "compute", min(a.cost, self.w.ledger.balance(payer)), cycle=self.w.cycle,
                                   kind="appraisal", memo=v.id)
        if a.model and a.usage:
            self.w.events.publish(ev.ModelCalled("appraiser", "appraiser", a.model, a.usage.input_tokens,
                                                 a.usage.output_tokens, None, a.cost, a.ms, a.real))
            if a.real:
                self.w.meter.record_real("appraiser", a.price_as or a.model, a.usage, cycle=self.w.cycle)
        if v.reward == 0:
            self.decide(v, approved=False)

    def _approve_best(self) -> None:
        waiting = sorted((v for v in self.w.ventures.values() if v.status == VentureStatus.PENDING and v.score is not None),
                         key=lambda v: (-v.score, v.id))
        for i, v in enumerate(waiting):
            if i < self.w.params.ventures.venture_budget:
                self.decide(v, approved=True)
            else:
                self.w.events.publish(ev.VentureWaiting(v))

    def decide(self, v: Venture, approved: bool) -> None:
        if not approved:
            v.status = VentureStatus.REJECTED
            self.w.events.publish(ev.VentureRejected(v))
            return
        job = MarketJob(f"V{self.w.ids.next('venture')}", v.title, v.reward,
                        {c: Part(c, spec, rubric) for c, spec, rubric in v.parts}, posted=self.w.cycle, deadline=self.w.cycle)
        job.claim(v.proposer, deadline=self.w.cycle + self.w.params.market.job_ttl)
        self.w.jobs[job.id] = job
        v.status, v.job_id = VentureStatus.APPROVED, job.id
        self.w.events.publish(ev.VentureApproved(v, job))
