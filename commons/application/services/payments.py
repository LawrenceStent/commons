"""Payments: passing work is paid as the society's economy says (a policy from commons/domain/economy.py): at once, or
at the end of the cycle in shares of a pool. Revenue splits by the treasury's rule; paid work is recorded for the
scorecard and, every so often, set aside for the operator to rate."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from commons.domain.market import MarketJob
from commons.domain.money import Micros
from commons.domain.status import (
    JobStatus,
)

if TYPE_CHECKING:
    from commons.application.world import World


class Payments:
    def __init__(self, world: World):
        self.w = world
        self.payment_queue = []  # passing jobs waiting to be paid at the end of the cycle

    def pool_balance(self) -> int:
        return self.w.ledger.balance(self.w.payment.pool) if self.w.payment.pool else 0

    def fund(self) -> None:
        """The economy's funder tops up its pool, if it keeps one. Under the lock."""
        if self.w.payment.pool and (amount := self.w.payment.funding(self.pool_balance())) > 0:
            self.w.ledger.transfer(self.w.payment.funder, self.w.payment.pool, amount, cycle=self.w.cycle, kind="grant",
                                 memo="budget")

    def settle_queue(self) -> None:
        """Pay the work that waited for the end of the cycle, in the shares the economy gives it. Under the lock."""
        queue = [j for jid in self.payment_queue if (j := self.w.jobs.get(jid)) is not None and j.status == JobStatus.GRADED]
        self.payment_queue = []
        if not queue:
            return
        values = {j.id: j.value(self.w.params.quality_pay) for j in queue}
        pool, total = self.pool_balance(), sum(values.values())
        shares = self.w.payment.shares(values, pool)
        for j in sorted(queue, key=lambda j: j.id):
            self.pay(j, payout=shares[j.id])
        self.w.hub.emit("grants.award", self.w.cycle, pool=pool, asked=total, paid=min(pool, total), jobs=len(queue))

    def pay(self, job: MarketJob, payout: Micros | None = None) -> None:
        prime = job.prime
        weights: Counter[str] = Counter()
        for part in job.parts.values():
            for pid in part.cites:
                pb = self.w.library.get(pid)
                if pb and pb.author != prime and pb.author in self.w.communities:  # seeded playbooks earn no one royalties
                    weights[pb.author] += 1
                    pb.uses += 1
        # the commons takes only what it needs: no treasury share while the treasury is at its reserve
        tax = self.w.ledger.balance("treasury") < self.w.params.treasury_reserve
        mean = job.mean_score
        if payout is None:
            payout = job.value(self.w.params.quality_pay)  # pay scales with quality
        split = self.w.ledger.settle_revenue(prime, payout, cycle=self.w.cycle, royalties=dict(weights), memo=job.id, tax=tax,
                                           source=self.w.payment.source)
        share = split.earner
        self.w.board.settle_bond(job, returned=True)
        job.pay()
        self.w.jobs_done += 1
        self.w.stat(prime, "earned", share)
        track = self.w.communities[prime].deliveries
        for cap, part in job.parts.items():
            if part.source == "self":
                track[cap] = track.get(cap, 0) + 1
        self.w.tell(prime, "job_paid", f"{job.id} passed grading (mean score {mean:.2f}); {self.w.payment.payer} paid {payout} "
                   f"of {job.reward}, you received {share}", job.id)
        record = {"job": job.id, "title": job.title, "prime": prime, "cycle": self.w.cycle, "scores": dict(job.scores),
                  "payout": payout, "parts": {cap: {"by": self.done_by(job, part), "spec": part.spec,
                                                    "text": (part.artifact or "")[:4000]}
                                              for cap, part in sorted(job.parts.items())}}
        self.w.outputs.append(record)
        if self.w.ratings:
            self.w.ratings.sample(record)
        for author, amount in split.royalties.items():
            self.w.stat(author, "earned", amount)
            self.w.royalties_paid[author] = self.w.royalties_paid.get(author, 0) + amount
            self.w.tell(author, "royalty", f"your playbook was used in {job.id}: {amount}", job.id)
        self.w.hub.emit("market.job", self.w.cycle, id=job.id, stage="paid", prime=prime, caps=sorted(job.parts),
                      reward=job.reward, payout=payout, scores=job.scores, royalties=split.royalties, taxed=tax)

    def done_by(self, job: MarketJob, part) -> str:
        if part.source in (None, "self"):
            return job.prime
        c = self.w.contracts.get(part.source)
        return c.winner if c and c.winner else job.prime
