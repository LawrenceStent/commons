"""The job board: jobs posted, claimed, finished, paid or failed.

Claims are registered during a cycle and allocated at its end, by rule rather than by who answered first: most trusted,
then best fit, then least loaded, ties by a draw seeded from the job. The winner posts a bond, returned when the job is
paid and forfeited if it fails. The rules of each move are the job aggregate's (commons/domain/market.py)."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from commons.domain.community import Community
from commons.domain.market import MarketJob
from commons.domain.status import (
    ContractStatus,
    JobStatus,
)
from commons.domain.treasury import bond_for
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.world import World


class JobBoard:
    def __init__(self, world: World):
        self.w = world
        self.claims = {}  # job id -> {claimant: cycle claimed}, allocated at cycle end

    def post(self) -> None:
        p = self.w.params
        for _ in range(p.jobs_per_cycle):
            job = self.w.pack.work_source.new_job(self.w.rng, f"J{self.w.ids.next('job')}", self.w.cycle, p.job_reward, p.board_ttl,
                                                p.parts_per_job)
            self.w.jobs[job.id] = job
            self.w.hub.emit("market.job", self.w.cycle, id=job.id, stage="posted", caps=sorted(job.parts), reward=job.reward)

    def expire_overdue(self) -> None:
        """Jobs nobody claimed in time expire; claimed jobs past their deadline fail."""
        now = self.w.cycle
        for job in self.w.jobs.values():
            if job.status == JobStatus.OPEN and now > job.deadline:
                job.expire()
                self.w.jobs_expired += 1
                self.w.hub.emit("market.job", now, id=job.id, stage="expired", caps=sorted(job.parts), reward=job.reward)
            elif job.status == JobStatus.CLAIMED and now > job.deadline and job.id not in self.w.grading.awaiting_grade:
                self.fail(job, "missed its deadline")

    def prune(self) -> None:
        """Drop closed jobs after a while, so memory stays flat on long runs."""
        cutoff = self.w.cycle - self.w.params.retain
        for k in [k for k, j in self.w.jobs.items() if j.status not in (JobStatus.OPEN, JobStatus.CLAIMED, JobStatus.GRADED) and j.deadline < cutoff]:
            del self.w.jobs[k]

    def finish(self, job: MarketJob) -> None:
        if not job.passed(self.w.params.pass_score):
            self.fail(job, f"a part failed grading ({', '.join(f'{k} {v:.2f}' for k, v in job.scores.items())})")
            return
        if not self.w.payment.pays_at_once:
            job.await_grants()
            self.w.payments.payment_queue.append(job.id)
            self.w._tell(job.prime, "job_graded", f"{job.id} passed grading; {self.w.payment.queued}", job.id)
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
            draw = random.Random(f"{p.seed}:{self.w.cycle}:{jid}")  # its own seed: the world's dice stay untouched

            def key(name: str) -> tuple:
                c = self.w.communities[name]
                fit = sum(cap in c.capabilities for cap in job.parts) / len(job.parts)
                return (-round(self.w._standing(name), 3), -fit, self.held_jobs(name), draw.random())

            bond = bond_for(job.reward, p.claim_bond)
            for name in sorted(sorted(claimants), key=key):
                c = self.w.communities[name]
                if self.held_jobs(name) >= self.claim_limit(c):
                    continue
                if bond:
                    try:
                        self.w.ledger.transfer(purse(name), "escrow", bond, cycle=self.w.cycle, kind="bond", memo=jid)
                    except InsufficientFunds:
                        self.w._tell(name, "claim_lost", f"you couldn't post the {bond} bond for {jid}", jid)
                        continue
                job.claim(name, deadline=self.w.cycle + p.job_ttl, bond=bond)
                self.w._tell(name, "claim_won", f"{jid} is yours (bond {bond}, returned when it's paid); "
                           f"submit every part by cycle {job.deadline}", jid)
                for other in claimants:
                    if other != name:
                        self.w._tell(other, "claim_lost", f"{jid} went to {name} (more trusted, a better fit, or less loaded)", jid)
                self.w.hub.emit("market.job", self.w.cycle, id=jid, stage="claimed", prime=name, caps=sorted(job.parts),
                              reward=job.reward, claimants=sorted(claimants), bond=bond)
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
        for c in self.w.contracts.values():
            if c.job_id == job.id and c.status == ContractStatus.OPEN:
                c.withdraw(at=self.w.cycle)
                self.w.contract_net.stage(c, c.status)
        self.w._tell(job.prime, "job_failed", f"{job.id} failed: {why}", job.id)
        self.w.hub.emit("market.job", self.w.cycle, id=job.id, stage="failed", prime=job.prime, caps=sorted(job.parts),
                      reward=job.reward, why=why)
