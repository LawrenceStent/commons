"""The contract-net: how a prime buys a part of a job from another co-op.

The contract-net spans cycles, and every stage has a deadline, so no one can stall another:
    open       bids arrive; the prime awards from the next cycle   -> expired after `bid_window`
    awarded    advance paid; contractor delivers                    -> failed after `deliver_ttl`:
               the prime keeps its complaint, the advance is gone
    delivered  the grader judges it (or, with prime reviews, the prime) -> accepted, rejected; if the prime can't pay
               it has defaulted
A rejection may go to a paid audit. The rules of each move are the Contract aggregate's (commons/domain/contract.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.graders import GradingError
from commons.application.observation import (
    Outcome,
)
from commons.domain.contract import Contract
from commons.domain.ids import ContractId, JobId
from commons.domain.market import MarketJob
from commons.domain.money import Micros
from commons.domain.status import (
    ContractStatus,
    JobStatus,
)
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.world import World


class ContractNet:
    def __init__(self, world: World):
        self.w = world

    def stage(self, c: Contract, stage: str, **kw) -> None:
        self.w.hub.emit("contract.stage", self.w.cycle, id=c.id, capability=c.capability, prime=c.prime,
                      winner=c.winner, stage=stage, price=c.price, max_price=c.max_price, bids=dict(c.bids), **kw)

    def expire_overdue(self) -> None:
        """Every contract stage has a deadline, so no one can stall another."""
        now = self.w.cycle
        for c in list(self.w.contracts.values()):
            if c.deadline >= now:
                continue
            if c.status == ContractStatus.OPEN:
                c.expire(at=now)
                self.stage(c, c.status)
                self.w.tell(c.prime, "expired", f"{c.id} closed with no award", c.id)
            elif c.status == ContractStatus.AWARDED:
                # non-delivery is objective: the substrate files the prime's complaint for it
                c.fail(at=now)
                self.stage(c, c.status)
                self.w.rep.attest(c.prime, c.winner, c.capability, 0.0)
                self.w.tell(c.prime, "failed", f"{c.winner} never delivered {c.id}", c.id)
                self.w.tell(c.winner, "failed", f"you missed the delivery deadline on {c.id}", c.id)
            elif c.status == ContractStatus.DELIVERED and c.id not in self.w.grading.pending_reviews:
                if self.pay_remainder(c):
                    self.close_review(c, True, "accepted by default: the prime didn't review in time")
                else:
                    self.default(c)

    def prune(self) -> None:
        """Drop closed contracts after a while."""
        cutoff = self.w.cycle - self.w.params.retain
        for k in [k for k, c in self.w.contracts.items() if c.closed is not None and c.closed < cutoff]:
            del self.w.contracts[k]

    def contracts_for(self, job_id: JobId, capability: str, statuses: tuple[str, ...]) -> list[Contract]:
        return [c for c in self.w.contracts.values()
                if c.job_id == job_id and c.capability == capability and c.status in statuses]

    def open(self, cid: ContractId, job: MarketJob, capability: str, prime: str, max_price: Micros, advance_frac: float) -> None:
        part = job.parts[capability]
        c = Contract(cid, job.id, capability, prime, part.spec, part.rubric, max_price, advance_frac,
                     announced=self.w.cycle, deadline=self.w.cycle + self.w.params.bid_window)
        self.w.contracts[cid] = c
        self.stage(c, ContractStatus.OPEN)

    def award(self, c: Contract, bidder: str, price: Micros, advance: Micros) -> None:
        c.award(bidder, price, advance, deliver_by=self.w.cycle + self.w.params.deliver_ttl)
        self.w.stat(bidder, "won")
        self.w.stat(bidder, "earned", advance)
        self.w.tell(bidder, "awarded", f"you won {c.id} at {price}; advance {advance} paid; deliver by cycle {c.deadline}", c.id)
        for loser in c.bids:
            if loser != bidder:
                self.w.tell(loser, "bid_lost", f"{c.id} went to another bidder", c.id)
        self.stage(c, ContractStatus.AWARDED)

    def deliver(self, c: Contract, artifact: str, cites: tuple[str, ...]) -> None:
        c.deliver(artifact, cites, review_by=self.w.cycle + self.w.params.review_ttl)
        if self.w.params.grader_reviews:
            self.w.grading.pending_reviews[c.id] = 0
            self.w.tell(c.prime, "delivered", f"{c.winner} delivered {c.id}; the grader judges it at the end of this cycle", c.id)
        else:
            self.w.tell(c.prime, "delivered", f"{c.winner} delivered {c.id}; review by cycle {c.deadline}", c.id)
        self.stage(c, ContractStatus.DELIVERED)

    def pay_remainder(self, c: Contract) -> bool:
        owed = c.owed
        try:
            self.w.ledger.transfer(purse(c.prime), purse(c.winner), owed, cycle=self.w.cycle, kind="contract", memo=f"settle {c.id}")
        except InsufficientFunds:
            return False
        self.w.stat(c.winner, "earned", owed)
        return True

    def close_review(self, c: Contract, accept: bool, reason: str) -> None:
        (c.accept if accept else c.reject)(reason, at=self.w.cycle)
        self.stage(c, c.status)
        self.w.rep.attest(c.prime, c.winner, c.capability, 1.0 if accept else 0.0)
        if accept:
            self.w.stat(c.winner, "ok")
            track = self.w.communities[c.winner].deliveries
            track[c.capability] = track.get(c.capability, 0) + 1
            self.w.tell(c.winner, "accepted", f"{c.prime} accepted {c.id} and paid {c.owed}", c.id)
            job = self.w.jobs.get(c.job_id)
            if job and job.status == JobStatus.CLAIMED and job.parts[c.capability].artifact is None:
                job.fill(c.capability, c.artifact, source=c.id, cites=c.cites)
                self.w.grading.maybe_submit(job)
        else:
            self.w.tell(c.winner, "rejected", f"{c.prime} rejected {c.id}: {reason or 'no reason given'}", c.id)

    def audit(self, c: Contract, reason: str) -> Outcome:
        """File a dispute. The grader decides at the end of this cycle, outside the world's lock, so an
        audit never holds up other communities (in the third Qwen run one stalled a cycle for 9 minutes)."""
        c.file_dispute()
        self.w.grading.pending_audits[c.id] = {"reason": reason, "attempts": 0}
        self.stage(c, "audit_filed")
        self.w.tell(c.prime, "audit_filed", f"{c.winner} disputed your rejection of {c.id}; the grader decides this cycle", c.id)
        return Outcome(True, f"audit of {c.id} filed; the grader decides at the end of this cycle")

    def apply_audit(self, c: Contract, g, reason: str) -> None:
        """The verdict, under the lock. The commons ("audit") files its own first-hand evidence, so the
        verdict moves standing, not any one community's private view."""
        p = self.w.params
        if g.score < p.pass_score:
            self.w.rep.attest("audit", c.winner, c.capability, 0.0)
            self.stage(c, "audit_upheld", score=g.score)
            self.w.tell(c.prime, "audit", f"the audit upheld your rejection of {c.id} ({g.score:.2f})", c.id)
            self.w.tell(c.winner, "audit", f"the audit upheld the rejection of {c.id}: your delivery scored {g.score:.2f}; the fee is gone", c.id)
            return
        owed = c.owed
        try:
            # the treasury keeps the fee (it paid for the audit); the prime reimburses the contractor
            self.w.ledger.transfer(purse(c.prime), purse(c.winner), owed + p.audit_cost,
                                 cycle=self.w.cycle, kind="audit", memo=f"overturned {c.id}")
            paid = True
        except InsufficientFunds:
            paid = False
        self.w.rep.attest("audit", c.prime, c.capability, 0.0)
        self.w.rep.attest("audit", c.winner, c.capability, 1.0)
        if not paid:
            c.default(at=self.w.cycle)
            self.stage(c, c.status)
            self.w.tell(c.winner, "audit", f"the audit found for you on {c.id}, but {c.prime} can't pay", c.id)
            return
        self.w.stat(c.winner, "earned", owed + p.audit_cost)
        self.w.stat(c.winner, "ok")
        c.overturn(f"overturned on audit ({g.score:.2f}): {reason}", at=self.w.cycle)
        self.stage(c, c.status)
        self.stage(c, "audit_overturned", score=g.score)
        self.w.tell(c.prime, "audit", f"the audit overturned your rejection of {c.id}; you paid {owed} plus the {p.audit_cost} fee", c.id)
        job = self.w.jobs.get(c.job_id)
        if job and job.status == JobStatus.CLAIMED and job.parts[c.capability].artifact is None:
            job.fill(c.capability, c.artifact, source=c.id, cites=c.cites)
            self.w.grading.maybe_submit(job)
        self.w.tell(c.winner, "audit", f"the audit found for you on {c.id} ({g.score:.2f}): {c.prime} paid {owed} plus your {p.audit_cost} fee", c.id)

    def settle_review(self, cid: ContractId, g) -> None:
        """The grader's verdict on a delivery decides the contract (option B). Under the lock."""
        c = self.w.contracts.get(cid)
        if c is None or c.status != ContractStatus.DELIVERED:
            self.w.grading.pending_reviews.pop(cid, None)
            return
        if isinstance(g, GradingError):
            self.w.grading.pending_reviews[cid] += 1
            if self.w.grading.pending_reviews[cid] < self.w.params.grade_retries:
                return
            self.w.grading.pending_reviews.pop(cid)
            # the grader stayed down: accept by default, so contractors aren't punished for an outage
            if self.pay_remainder(c):
                self.close_review(c, True, "accepted by default: the grader was unavailable")
            else:
                self.default(c)
            return
        self.w.grading.pending_reviews.pop(cid)
        self.w.grading.charge(g, job=c.job_id, part=c.capability, payers=("treasury", purse(c.prime)))
        if g.score < self.w.params.pass_score:
            self.close_review(c, False, f"failed grading ({g.score:.2f}): {g.reason}"[:300])
            return
        if not self.pay_remainder(c):
            self.default(c)
            return
        job = self.w.jobs.get(c.job_id)
        if job is not None:
            job.record_score(c.capability, g.score)  # reused when the job is graded: no part is graded twice
        self.close_review(c, True, f"passed grading ({g.score:.2f}): {g.reason}"[:300])

    def default(self, c: Contract) -> None:
        c.default(at=self.w.cycle)
        self.stage(c, c.status)
        self.w.rep.attest(c.winner, c.prime, c.capability, 0.0)
        c.rated_by_winner()
        self.w.tell(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)

    def settle_audit(self, cid: ContractId, g) -> None:
        entry = self.w.grading.pending_audits[cid]
        c = self.w.contracts.get(cid)
        if c is None:
            self.w.grading.pending_audits.pop(cid)
            return
        if isinstance(g, GradingError):
            entry["attempts"] += 1
            if entry["attempts"] >= self.w.params.grade_retries:
                self.w.grading.pending_audits.pop(cid)
                c.drop_dispute()  # it may be filed again
                self.w.ledger.transfer("treasury", purse(c.winner), self.w.params.audit_cost, cycle=self.w.cycle, kind="audit",
                                     memo=f"refund {cid}")
                self.w.tell(c.winner, "audit", f"the grader was unavailable for the audit of {cid}; your fee was refunded", cid)
            return
        self.w.grading.pending_audits.pop(cid)
        self.w.grading.charge(g, job=c.job_id, part=c.capability, payers=("treasury", purse(c.winner)), audit=cid)
        self.apply_audit(c, g, entry["reason"])
