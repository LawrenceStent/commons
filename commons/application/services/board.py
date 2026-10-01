"""The job board: jobs posted, claimed, finished, paid or failed.

Claims are registered during a cycle and allocated at its end, by rule rather than by who answered first: most trusted,
then best fit, then least loaded, ties by a draw seeded from the job. The winner posts a bond, returned when the job is
paid and forfeited if it fails. The rules of each move are the job aggregate's (commons/domain/market.py)."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.community import Community
from commons.domain.market import MarketJob
from commons.domain.status import JobStatus
from commons.domain.treasury import bond_for
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.society import World


class JobBoard:
    def __init__(self, world: World):
        self.w = world
        self.claims = {}  # job id -> {claimant: cycle claimed}, allocated at cycle end

    def post(self) -> None:
        p = self.w.params
        for _ in range(p.market.jobs_per_cycle):
            job = self.w.pack.work_source.new_job(self.w.rng, f"J{self.w.ids.next('job')}", self.w.cycle, p.market.job_reward, p.market.board_ttl,
                                                p.market.parts_per_job)
            self.w.jobs[job.id] = job
            self.w.events.publish(ev.JobPosted(job))

    def expire_overdue(self) -> None:
        """Jobs nobody claimed in time expire; claimed jobs past their deadline fail."""
        now = self.w.cycle
        for job in self.w.jobs.values():
            if job.status == JobStatus.OPEN and now > job.deadline:
                job.expire()
                self.w.jobs_expired += 1
                self.w.events.publish(ev.JobExpired(job))
            elif job.status == JobStatus.CLAIMED and now > job.deadline and job.id not in self.w.grading.awaiting_grade:
                self.fail(job, "missed its deadline")

    def prune(self) -> None:
        """Drop closed jobs after a while, so memory stays flat on long runs."""
        cutoff = self.w.cycle - self.w.params.storage.retain
        for k in [k for k, j in self.w.jobs.items() if j.status not in (JobStatus.OPEN, JobStatus.CLAIMED, JobStatus.GRADED) and j.deadline < cutoff]:
            del self.w.jobs[k]

    def finish(self, job: MarketJob) -> None:
        if not job.passed(self.w.params.market.pass_score):
            self.fail(job, f"a part failed grading ({', '.join(f'{k} {v:.2f}' for k, v in job.scores.items())})")
            return
        if not self.w.payment.pays_at_once:
            job.await_grants()
            self.w.payments.payment_queue.append(job.id)
            self.w.events.publish(ev.JobAwaitingPayment(job, self.w.payment.queued))
            return
        self.w.payments.pay(job)

    def held_jobs(self, name: str) -> int:
        return sum(j.prime == name and j.status == JobStatus.CLAIMED for j in self.w.jobs.values())

    def claim_limit(self, c: Community) -> int:
        return max(2, c.thinking)

    def pending_claims(self, name: str) -> list[str]:
        return [jid for jid, who in self.claims.items() if name in who]

    def allocate(self) -> None:
        """Give each claimed job to one claimant, by rule rather than by who answered first."""
        p = self.w.params
        for jid in sorted(self.claims):
            job, claimants = self.w.jobs.get(jid), self.claims.pop(jid)
            if job is None or job.status != JobStatus.OPEN:
                continue
            draw = random.Random(f"{p.run.seed}:{self.w.cycle}:{jid}")  # its own seed: the world's dice stay untouched

            def key(name: str) -> tuple:
                c = self.w.communities[name]
                fit = sum(cap in c.capabilities for cap in job.parts) / len(job.parts)
                return (-round(self.w.standing(name), 3), -fit, self.held_jobs(name), draw.random())

            bond = bond_for(job.reward, p.market.claim_bond)
            for name in sorted(sorted(claimants), key=key):
                c = self.w.communities[name]
                if self.held_jobs(name) >= self.claim_limit(c):
                    continue
                if bond:
                    try:
                        self.w.ledger.transfer(purse(name), "escrow", bond, cycle=self.w.cycle, kind="bond", memo=jid)
                    except InsufficientFunds:
                        self.w.events.publish(ev.BondUnaffordable(name, job, bond))
                        continue
                job.claim(name, deadline=self.w.cycle + p.market.job_ttl, bond=bond)
                self.w.events.publish(ev.JobClaimed(job, tuple(claimants), bond))
                break

    def settle_bond(self, job: MarketJob, returned: bool) -> None:
        if not (bond := job.release_bond()):
            return
        dest = purse(job.prime) if returned else "treasury"
        self.w.ledger.transfer("escrow", dest, bond, cycle=self.w.cycle, kind="bond",
                             memo=f"{'return' if returned else 'forfeit'} {job.id}")

    def fail(self, job: MarketJob, why: str) -> None:
        self.settle_bond(job, returned=False)
        job.fail()
        self.w.jobs_failed += 1
        self.w.contract_net.withdraw_open(job.id)
        self.w.events.publish(ev.JobFailed(job, why))
