"""The actions executor: the only way a policy touches the world.

Every call is validated here, costs capacity where it represents work, is signed and
published on the bus where the protocol has a message for it, and moves money only
through the ledger. Failures come back as readable Outcomes, never exceptions, so an
LLM can see why something didn't happen and try something else.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from protocol import Envelope, Message
from protocol.contract import Announce, Award, Bid, Deliver
from protocol.knowledge import Cite, Publish
from protocol.reputation import Attest, Dispute
from sim import population
from society.observation import Outcome
from substrate.bus import RateLimited
from substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from sim.engine import Contract, World
    from society.community import Community

MAX_ARTIFACT = 4000
MAX_NOTE = 500


class Actions:
    def __init__(self, world: World, me: Community):
        self.w = world
        self.me = me

    # ── plumbing ───────────────────────────────────────────────
    def _send(self, msg: Message) -> bool:
        try:
            self.w.bus.publish(Envelope.seal(self.me.identity, msg, self.w.cycle))
            return True
        except RateLimited:
            return False

    def _use_capacity(self) -> Outcome | None:
        if self.me.capacity <= 0:
            return Outcome(False, "no capacity left this turn: every funded member is busy")
        self.me.capacity -= 1
        return None

    def _contract(self, contract_id: str) -> Contract | None:
        return self.w.contracts.get(contract_id)

    def _cites_ok(self, cites: tuple[str, ...]) -> Outcome | None:
        unknown = [c for c in cites if c not in self.w.library]
        return Outcome(False, f"unknown playbook(s): {', '.join(unknown)}") if unknown else None

    # ── market ─────────────────────────────────────────────────
    def claim(self, job_id: str) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.status != "open":
            return Outcome(False, f"job {job_id} is not on the board")
        if err := self._use_capacity():
            return err
        job.prime, job.status = self.me.name, "claimed"
        job.deadline = self.w.cycle + self.w.params.job_ttl
        return Outcome(True, f"claimed {job_id}; submit all parts by cycle {job.deadline}", job_id)

    def do_part(self, job_id: str, capability: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.prime != self.me.name or job.status != "claimed":
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
        for c in self.w.contracts_for(job_id, capability, ("open",)):
            c.status = "withdrawn"
        part.artifact, part.source, part.cites = artifact[:MAX_ARTIFACT], "self", tuple(cites)
        self.w.maybe_submit(job)
        return Outcome(True, f"{capability} part of {job_id} done")

    # ── contract-net ───────────────────────────────────────────
    def announce(self, job_id: str, capability: str, max_price: int, advance_frac: float) -> Outcome:
        job = self.w.jobs.get(job_id)
        if job is None or job.prime != self.me.name or job.status != "claimed":
            return Outcome(False, f"you are not working on job {job_id}")
        part = job.parts.get(capability)
        if part is None or part.artifact is not None:
            return Outcome(False, f"job {job_id} has no open {capability} part")
        if self.w.contracts_for(job_id, capability, ("open", "awarded", "delivered")):
            return Outcome(False, f"a contract for that part is already in progress")
        if max_price <= 0 or not 0 <= advance_frac <= 1:
            return Outcome(False, "max_price must be positive and advance_frac within 0..1")
        n = sum(1 for c in self.w.contracts.values() if c.job_id == job_id and c.capability == capability)
        cid = f"{job_id}.{capability}.{n + 1}"
        if not self._send(Announce(job_id=cid, capability=capability, reward=max_price,
                                   advance_frac=advance_frac, spec=part.spec)):
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        self.w.open_contract(cid, job, capability, self.me.name, max_price, advance_frac)
        return Outcome(True, f"announced {cid}; bids arrive from next turn", cid)

    def bid(self, contract_id: str, price: int) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.status != "open":
            return Outcome(False, f"contract {contract_id} is not open")
        if c.prime == self.me.name:
            return Outcome(False, "you can't bid on your own contract")
        if not self.me.can(c.capability):
            return Outcome(False, f"you lack the {c.capability} capability")
        if not 0 < price <= c.max_price:
            return Outcome(False, f"price must be between 1 and {c.max_price}")
        if err := self._use_capacity():
            return err
        if not self._send(Bid(job_id=contract_id, price=price)):
            self.me.capacity += 1
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        c.bids[self.me.name] = price
        return Outcome(True, f"bid {price} on {contract_id}")

    def award(self, contract_id: str, bidder: str) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.prime != self.me.name or c.status != "open":
            return Outcome(False, f"you have no open contract {contract_id}")
        if bidder not in c.bids:
            return Outcome(False, f"{bidder} did not bid on {contract_id}")
        if self.w.cycle <= c.announced:
            return Outcome(False, "wait a cycle: other communities haven't had a turn to bid")
        price = c.bids[bidder]
        advance = round(price * c.advance_frac)
        try:
            self.w.ledger.transfer(purse(self.me.name), purse(bidder), advance, cycle=self.w.cycle,
                                   kind="contract", memo=f"advance {contract_id}")
        except InsufficientFunds:
            return Outcome(False, f"you can't cover the {advance} advance")
        self._send(Award(job_id=contract_id, winner=bidder, price=price, advance=advance))
        self.w.award_contract(c, bidder, price, advance)
        return Outcome(True, f"awarded {contract_id} to {bidder} at {price}; advance {advance} paid")

    def deliver(self, contract_id: str, artifact: str, cites: tuple[str, ...] = ()) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.winner != self.me.name or c.status != "awarded":
            return Outcome(False, f"you have no awarded contract {contract_id} to deliver")
        if err := self._cites_ok(tuple(cites)):
            return err
        if err := self._use_capacity():
            return err
        self._send(Deliver(job_id=contract_id, artifact={"text": artifact[:MAX_ARTIFACT]}, cites=list(cites)))
        for pid in cites:
            self._send(Cite(playbook_id=pid, job_id=contract_id))
        self.w.deliver_contract(c, artifact[:MAX_ARTIFACT], tuple(cites))
        return Outcome(True, f"delivered {contract_id}; {c.prime} reviews by cycle {c.deadline}")

    def review(self, contract_id: str, accept: bool, reason: str = "") -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.prime != self.me.name or c.status != "delivered":
            return Outcome(False, f"you have no delivery {contract_id} to review")
        if accept and not self.w.pay_remainder(c):
            return Outcome(False, f"you can't pay the {c.price - c.advance} remainder; "
                                  f"it defaults at cycle {c.deadline} if still unpaid")
        self._send(Attest(job_id=contract_id, subject=c.winner, capability=c.capability, outcome=1.0 if accept else 0.0))
        self.w.close_review(c, accept, reason[:300])
        return Outcome(True, f"{'accepted' if accept else 'rejected'} {contract_id}")

    def attest(self, contract_id: str, outcome: float) -> Outcome:
        c = self._contract(contract_id)
        if c is None or c.winner != self.me.name or c.status not in ("accepted", "rejected", "failed"):
            return Outcome(False, f"no closed contract {contract_id} where you were the contractor")
        if c.winner_attested:
            return Outcome(False, "you already rated this prime")
        outcome = min(1.0, max(0.0, float(outcome)))
        self._send(Attest(job_id=contract_id, subject=c.prime, capability=c.capability, outcome=outcome))
        self.w.rep.attest(self.me.name, c.prime, c.capability, outcome)
        c.winner_attested = True
        return Outcome(True, f"rated {c.prime} {outcome:.2f} on {contract_id}")

    def dispute(self, contract_id: str, reason: str) -> Outcome:
        """Take a rejection to audit. The grader judges the delivery against the part's rubric.
        Found for you: the prime pays what it owed plus your audit fee, and the audit counts
        against it. Found against you: you lose the fee, and the audit counts against you."""
        w, p = self.w, self.w.params
        c = self._contract(contract_id)
        if c is not None and c.winner == self.me.name and c.disputed:
            return Outcome(False, f"{contract_id} has already been audited")
        if c is None or c.winner != self.me.name or c.status != "rejected":
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
        return w.audit(c, reason[:300])

    # ── population ─────────────────────────────────────────────
    def propose_spawn(self, role: str) -> Outcome:
        if err := self._use_capacity():
            return err
        return population.propose_spawn(self.w, self.me, role)

    def second_spawn(self, proposal_id: str) -> Outcome:
        return population.second_spawn(self.w, self.me, proposal_id)

    def retire(self) -> Outcome:
        return population.retire(self.w, self.me)

    def fork(self, name: str, members: int, capabilities: tuple[str, ...], charter: str = "") -> Outcome:
        if err := self._use_capacity():
            return err
        return population.fork(self.w, self.me, name, int(members), tuple(capabilities), charter)

    def propose_merge(self, target: str) -> Outcome:
        if err := self._use_capacity():
            return err
        return population.propose_merge(self.w, self.me, target)

    def accept_merge(self, proposal_id: str) -> Outcome:
        return population.accept_merge(self.w, self.me, proposal_id)

    def learn(self, capability: str, playbook_id: str | None = None) -> Outcome:
        if err := self._use_capacity():
            return err
        return population.learn(self.w, self.me, capability, playbook_id)

    # ── knowledge ──────────────────────────────────────────────
    def publish(self, capability: str, title: str, text: str) -> Outcome:
        if not self.me.can(capability):
            return Outcome(False, f"you can only publish methods for capabilities you have")
        if any(p.author == self.me.name and p.capability == capability for p in self.w.library.values()):
            return Outcome(False, f"you already have a {capability} playbook in the library")
        cost = self.w.params.publish_cost
        pid = hashlib.sha256(f"{self.me.name}:{capability}:{text}".encode()).hexdigest()[:10]
        if not self._send(Publish(playbook_id=pid, capability=capability, title=title[:120], content_hash=pid)):
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        try:
            self.w.meter.charge(self.me.name, cost, cycle=self.w.cycle, memo=f"publish {pid}")
        except InsufficientFunds:
            return Outcome(False, f"publishing costs {cost}; you can't afford it")
        self.w.add_playbook(pid, self.me.name, capability, title[:120], text[:MAX_ARTIFACT])
        return Outcome(True, f"published playbook {pid}; you earn royalties whenever it is cited", pid)

    def read_playbook(self, playbook_id: str) -> Outcome:
        pb = self.w.library.get(playbook_id)
        if pb is None:
            return Outcome(False, f"no playbook {playbook_id}")
        return Outcome(True, pb.text, pb.id)

    # ── runtime hooks (not tools: the LLM runtime calls these about itself) ──
    def record_call(self, role: str, model: str, price_as: str, usage, real: bool, ms: int | None = None,
                    cache_hit: float | None = None) -> int:
        """Charge a model call to this community: notionally always, in USD too when real.
        Raises InsufficientFunds when the purse can't pay, and KillSwitch at a ceiling."""
        cost = self.w.meter.charge_usage(self.me.name, price_as, usage, cycle=self.w.cycle, real=real)
        self.w.hub.emit("llm.call", self.w.cycle, community=self.me.name, role=role, model=model,
                        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                        cache_read=usage.cache_read_input_tokens, cache_hit=cache_hit, cost=cost, ms=ms, real=real)
        return cost

    def observe(self):
        """A fresh view mid-turn: after a claim or an award, the start-of-turn observation is stale."""
        return self.w.observe(self.me)

    def record_transcript(self, entries: list[dict]) -> None:
        self.w.transcripts[self.me.name].append({"cycle": self.w.cycle, "entries": entries[-80:]})
        tools = [e for e in entries if e["kind"] == "tool"]
        self.w.hub.emit("llm.turn", self.w.cycle, community=self.me.name, tools=len(tools),
                        ok=sum(e["ok"] for e in tools), names=[e["name"] for e in tools],
                        said=sum(e["kind"] == "say" for e in entries), errors=[e["text"] for e in entries if e["kind"] == "error"],
                        entries=entries[-80:])

    # ── self ───────────────────────────────────────────────────
    def note(self, text: str) -> Outcome:
        self.w.journal[self.me.name].append(f"[cycle {self.w.cycle}] {text[:MAX_NOTE]}")
        return Outcome(True, "noted")

    def spend(self, amount: int, memo: str) -> Outcome:
        try:
            self.w.meter.charge(self.me.name, amount, cycle=self.w.cycle, memo=memo)
            return Outcome(True, f"spent {amount}")
        except InsufficientFunds:
            return Outcome(False, f"can't afford {amount}")
