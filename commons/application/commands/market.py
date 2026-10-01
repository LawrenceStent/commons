"""Jobs and the contract-net: claiming, doing parts, buying parts from others, delivering, reviewing,
rating and disputing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.commands.base import MAX_ARTIFACT, CommandBase
from commons.application.commands.pipeline import command
from commons.application.observation import Outcome
from commons.domain.ids import ContractId, JobId
from commons.domain.money import Micros
from commons.domain.status import LIVE_CONTRACT, ContractStatus, JobStatus
from commons.domain.treasury import bond_for
from commons.protocol.contract import Announce, Award, Bid, Deliver
from commons.protocol.knowledge import Cite
from commons.protocol.reputation import Attest, Dispute
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    pass


class MarketCommands(CommandBase):
    @command()
    def claim(self, job_id: JobId) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.status != JobStatus.OPEN:
            return Outcome(False, f"job {job_id} is not on the board")
        # at most two open jobs (or one per awake member), counting claims waiting for allocation
        w, p = self.w, self.w.params
        held = w.board.held_jobs(self.me.name) + (len(w.board.pending_claims(self.me.name)) if p.claim_allocation else 0)
        limit = w.board.claim_limit(self.me)
        if held >= limit:
            return Outcome(False, f"you already hold or have claimed {held} jobs, the most you can (two, or one per "
                                  f"awake member); finish one first")
        bond = bond_for(job.reward, p.claim_bond)
        if bond and w.ledger.balance(purse(self.me.name)) < bond:
            return Outcome(False, f"claiming {job_id} needs a {bond} bond if you win it; you can't afford it")
        if p.claim_allocation and self.me.name in w.board.claims.get(job_id, {}):
            return Outcome(False, f"you have already claimed {job_id}; it is allocated at the end of the cycle")
        if err := self._use_capacity():
            return err
        if p.claim_allocation:
            w.board.claims.setdefault(job_id, {})[self.me.name] = w.cycle
            return Outcome(True, f"claim on {job_id} registered; jobs are allocated at the end of the cycle to the most "
                                 f"trusted, best-fitting claimant (bond {bond} if you win)", job_id)
        job.claim(self.me.name, deadline=w.cycle + p.job_ttl)
        return Outcome(True, f"claimed {job_id}; submit all parts by cycle {job.deadline}", job_id)

    @command()
    def do_part(self, job_id: JobId, capability: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.prime != self.me.name or job.status != JobStatus.CLAIMED:
            return Outcome(False, f"you are not working on job {job_id}")
        part = job.parts.get(capability)
        if part is None:
            return Outcome(False, f"job {job_id} has no {capability} part")
        if part.artifact is not None:
            return Outcome(False, f"the {capability} part is already done")
        if not self.me.can(capability):
            return Outcome(False, f"you lack the {capability} capability; announce a contract instead")
        if err := self._cites_ok(tuple(cites)):
            return err
        if err := self._use_capacity():
            return err
        for c in self.w.contract_net.contracts_for(job_id, capability, (ContractStatus.OPEN,)):
            c.withdraw(at=None)  # left unclosed, as before: see REFACTOR-PLAN §7
        job.fill(capability, artifact[:MAX_ARTIFACT], source="self", cites=tuple(cites))
        self.w.grading.maybe_submit(job)
        return Outcome(True, f"{capability} part of {job_id} done")

    @command()
    def announce(self, job_id: JobId, capability: str, max_price: Micros, advance_frac: float) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.prime != self.me.name or job.status != JobStatus.CLAIMED:
            return Outcome(False, f"you are not working on job {job_id}")
        part = job.parts.get(capability)
        if part is None or part.artifact is not None:
            return Outcome(False, f"job {job_id} has no open {capability} part")
        if self.w.contract_net.contracts_for(job_id, capability, LIVE_CONTRACT):
            return Outcome(False, "a contract for that part is already in progress")
        if max_price <= 0 or not 0 <= advance_frac <= 1:
            return Outcome(False, "max_price must be positive and advance_frac within 0..1")
        n = sum(1 for c in self.w.contracts.values() if c.job_id == job_id and c.capability == capability)
        cid = f"{job_id}.{capability}.{n + 1}"
        if not self._send(Announce(job_id=cid, capability=capability, reward=max_price,
                                   advance_frac=advance_frac, spec=part.spec)):
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        self.w.contract_net.open(cid, job, capability, self.me.name, max_price, advance_frac)
        return Outcome(True, f"announced {cid}; bids arrive from next turn", cid)

    @command()
    def bid(self, contract_id: ContractId, price: Micros) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.status != ContractStatus.OPEN:
            return Outcome(False, f"contract {contract_id} is not open")
        if c.prime == self.me.name:
            return Outcome(False, "you can't bid on your own contract")
        if not self.me.can(c.capability):
            return Outcome(False, f"you lack the {c.capability} capability")
        if not 0 < price <= c.max_price:
            return Outcome(False, f"price must be between 1 and {c.max_price}")
        ok, why = self.w.eligible(c.prime, self.me.name, c.capability)
        if not ok:
            return Outcome(False, f"the commons refuses your bid: {why}")
        if err := self._use_capacity():
            return err
        if not self._send(Bid(job_id=contract_id, price=price)):
            self.me.capacity += 1
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        c.bid(self.me.name, price)
        return Outcome(True, f"bid {price} on {contract_id}")

    @command()
    def award(self, contract_id: ContractId, bidder: str) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.prime != self.me.name or c.status != ContractStatus.OPEN:
            return Outcome(False, f"you have no open contract {contract_id}")
        if bidder not in c.bids:
            return Outcome(False, f"{bidder} did not bid on {contract_id}")
        if self.w.cycle <= c.announced:
            return Outcome(False, "wait a cycle: other communities haven't had a turn to bid")
        ok, why = self.w.eligible(self.me.name, bidder, c.capability)  # standing can fall between bid and award
        if not ok:
            return Outcome(False, f"the commons refuses this award: {why}; choose another bidder")
        price = c.bids[bidder]
        advance = round(price * c.advance_frac)
        try:
            self.w.ledger.transfer(purse(self.me.name), purse(bidder), advance, cycle=self.w.cycle,
                                   kind="contract", memo=f"advance {contract_id}")
        except InsufficientFunds:
            return Outcome(False, f"you can't cover the {advance} advance")
        self._send(Award(job_id=contract_id, winner=bidder, price=price, advance=advance))
        self.w.contract_net.award(c, bidder, price, advance)
        return Outcome(True, f"awarded {contract_id} to {bidder} at {price}; advance {advance} paid")

    @command()
    def deliver(self, contract_id: ContractId, artifact: str, cites: tuple[str, ...] = ()) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.winner != self.me.name or c.status != ContractStatus.AWARDED:
            return Outcome(False, f"you have no awarded contract {contract_id} to deliver")
        if err := self._cites_ok(tuple(cites)):
            return err
        if err := self._use_capacity():
            return err
        self._send(Deliver(job_id=contract_id, artifact={"text": artifact[:MAX_ARTIFACT]}, cites=list(cites)))
        for pid in cites:
            self._send(Cite(playbook_id=pid, job_id=contract_id))
        self.w.contract_net.deliver(c, artifact[:MAX_ARTIFACT], tuple(cites))
        return Outcome(True, f"delivered {contract_id}; {c.prime} reviews by cycle {c.deadline}")

    @command()
    def review(self, contract_id: ContractId, accept: bool, reason: str = "") -> Outcome:
        if self.w.params.grader_reviews:
            return Outcome(False, "the grader judges deliveries; there is nothing for you to review")
        c = self._contract(contract_id)
        if c is None or c.prime != self.me.name or c.status != ContractStatus.DELIVERED:
            return Outcome(False, f"you have no delivery {contract_id} to review")
        if accept and not self.w.contract_net.pay_remainder(c):
            return Outcome(False, f"you can't pay the {c.owed} remainder; "
                                  f"it defaults at cycle {c.deadline} if still unpaid")
        self._send(Attest(job_id=contract_id, subject=c.winner, capability=c.capability, outcome=1.0 if accept else 0.0))
        self.w.contract_net.close_review(c, accept, reason[:300])
        return Outcome(True, f"{'accepted' if accept else 'rejected'} {contract_id}")

    @command()
    def attest(self, contract_id: ContractId, outcome: float) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.winner != self.me.name or c.status not in (ContractStatus.ACCEPTED, ContractStatus.REJECTED, ContractStatus.FAILED):
            return Outcome(False, f"no closed contract {contract_id} where you were the contractor")
        if c.winner_attested:
            return Outcome(False, "you already rated this prime")
        outcome = min(1.0, max(0.0, float(outcome)))
        self._send(Attest(job_id=contract_id, subject=c.prime, capability=c.capability, outcome=outcome))
        self.w.rep.attest(self.me.name, c.prime, c.capability, outcome)
        c.rated_by_winner()
        return Outcome(True, f"rated {c.prime} {outcome:.2f} on {contract_id}")

    @command()
    def dispute(self, contract_id: ContractId, reason: str) -> Outcome:
        """Take a rejection to audit. The grader judges the delivery against the part's rubric.
        Found for you: the prime pays what it owed plus your audit fee, and the audit counts
        against it. Found against you: you lose the fee, and the audit counts against you."""
        w, p = self.w, self.w.params
        if p.grader_reviews:
            return Outcome(False, "deliveries are judged by the grader, so there is no prime's rejection to dispute")
        c = self._contract(contract_id)
        if c is not None and c.winner == self.me.name and c.disputed:
            return Outcome(False, f"{contract_id} has already been audited")
        if c is None or c.winner != self.me.name or c.status != ContractStatus.REJECTED:
            return Outcome(False, f"you have no rejected delivery {contract_id} to dispute")
        if w.cycle > c.closed + p.dispute_window:
            return Outcome(False, f"too late: disputes must be filed within {p.dispute_window} cycles of the rejection")
        try:
            w.ledger.transfer(purse(self.me.name), "treasury", p.audit_cost, cycle=w.cycle, kind="audit", memo=f"dispute {contract_id}")
        except InsufficientFunds:
            return Outcome(False, f"an audit costs {p.audit_cost}; you can't afford it")
        if not self._send(Dispute(job_id=contract_id, subject=c.prime, reason=reason[:300])):
            w.ledger.transfer("treasury", purse(self.me.name), p.audit_cost, cycle=w.cycle, kind="audit", memo=f"refund {contract_id}")
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        return w.contract_net.audit(c, reason[:300])
