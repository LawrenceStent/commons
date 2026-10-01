"""Ventures: work co-ops propose for themselves, appraised at the start of the next cycle (outside the world's lock),
priced by a fixed formula and approved by score, never by who asked first, up to `venture_budget` a cycle. The rules
are in commons/domain/ventures.py and commons/application/ventures.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.domain.market import MarketJob, Part
from commons.domain.status import (
    VentureStatus,
)
from commons.domain.ventures import AppraisalError, Venture
from commons.domain.ventures import value as venture_value
from commons.substrate.ledger import purse

if TYPE_CHECKING:
    from commons.application.world import World


class VentureDesk:
    def __init__(self, world: World):
        self.w = world

    def appraise(self) -> None:
        """Appraise waiting ventures outside the lock (a model call must never stall other communities),
        then decide under it: best score first, up to the market's budget for this cycle."""
        with self.w.lock:
            todo = [v for v in self.w.ventures.values() if v.status == VentureStatus.PENDING and v.score is None]
        def appraise(v):
            try:
                return v, self.w.appraiser.appraise(v)
            except AppraisalError as e:
                return v, e

        results = {}
        for v, a in self.w.grading.map_calls(appraise, todo):
            if isinstance(a, AppraisalError):
                with self.w.lock:
                    self.w._tell(v.proposer, "venture_delayed", f"{v.id} couldn't be appraised yet: {a}", v.id)
            else:
                results[v.id] = a
        with self.w.lock:
            p = self.w.params
            for vid, a in results.items():
                v = self.w.ventures[vid]
                v.score, v.reason, v.reward = a.score, a.reason, venture_value(a.score, p.job_reward, p.venture_min_score)
                if a.cost:
                    payer = "treasury" if self.w.ledger.balance("treasury") >= a.cost else purse(v.proposer)
                    self.w.ledger.transfer(payer, "compute", min(a.cost, self.w.ledger.balance(payer)), cycle=self.w.cycle,
                                         kind="appraisal", memo=vid)
                if a.model and a.usage:
                    self.w.hub.emit("llm.call", self.w.cycle, community="appraiser", role="appraiser", model=a.model,
                                  input_tokens=a.usage.input_tokens, output_tokens=a.usage.output_tokens,
                                  cache_hit=None, cost=a.cost, ms=a.ms, real=a.real)
                    if a.real:
                        self.w.meter.record_real("appraiser", a.price_as or a.model, a.usage, cycle=self.w.cycle)
                if v.reward == 0:
                    self.decide(v, approved=False)
            waiting = sorted((v for v in self.w.ventures.values() if v.status == VentureStatus.PENDING and v.score is not None),
                             key=lambda v: (-v.score, v.id))
            for i, v in enumerate(waiting):
                if i < p.venture_budget:
                    self.decide(v, approved=True)
                else:
                    self.w._tell(v.proposer, "venture_waiting", f"{v.id} scored {v.score} but the market's budget this "
                               f"cycle went to better-scored ventures; it stays in line", v.id)

    def decide(self, v: Venture, approved: bool) -> None:
        if not approved:
            v.status = VentureStatus.REJECTED
            self.w._tell(v.proposer, "venture_rejected", f"{v.id} {v.title!r} rejected (score {v.score}): {v.reason}", v.id)
            self.w.hub.emit("venture.decided", self.w.cycle, id=v.id, proposer=v.proposer, title=v.title, status=VentureStatus.REJECTED,
                          score=v.score, reward=0, reason=v.reason)
            return
        job = MarketJob(f"V{self.w.ids.next('venture')}", v.title, v.reward,
                        {c: Part(c, spec, rubric) for c, spec, rubric in v.parts}, posted=self.w.cycle, deadline=self.w.cycle)
        job.claim(v.proposer, deadline=self.w.cycle + self.w.params.job_ttl)
        self.w.jobs[job.id] = job
        v.status, v.job_id = VentureStatus.APPROVED, job.id
        self.w._tell(v.proposer, "venture_approved", f"{v.id} {v.title!r} approved as job {job.id}, reward {v.reward} µcr "
                   f"(score {v.score}: {v.reason}); deliver every part by cycle {job.deadline}", job.id)
        self.w.hub.emit("venture.decided", self.w.cycle, id=v.id, proposer=v.proposer, title=v.title, status=VentureStatus.APPROVED,
                      score=v.score, reward=v.reward, reason=v.reason, job=job.id)
        self.w.hub.emit("market.job", self.w.cycle, id=job.id, stage="venture", prime=v.proposer, caps=sorted(job.parts), reward=v.reward)
