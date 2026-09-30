"""The actions executor: the only way a policy touches the world.

Every call is validated here, costs capacity where it represents work, is signed and
published on the bus where the protocol has a message for it, and moves money only
through the ledger. Failures come back as readable Outcomes, never exceptions, so an
LLM can see why something didn't happen and try something else.
"""

from __future__ import annotations

import functools
import hashlib
import time
from typing import TYPE_CHECKING

from protocol import Envelope, Message
from protocol.contract import Announce, Award, Bid, Deliver
from protocol.knowledge import Cite, Publish
from protocol.reputation import Attest, Dispute
from sim import population
from sim.activity import logged
from sim.goals import MAX_ACTIVE_GOALS, MAX_STEPS, Goal, Idea, Step
from sim import ventures as ventures_mod
from society.observation import Outcome
from substrate.bus import RateLimited
from substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from sim.engine import Contract, World
    from society.community import Community

MAX_ARTIFACT = 4000
MAX_NOTE = 500


class Actions:
    actor = "scripted"  # the LLM runtime sets "steward"
    why = ""  # a rationale the runtime attaches to the next action, for the decision log

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
        # at most two open jobs (or one per awake member), counting claims waiting for allocation
        w, p = self.w, self.w.params
        held = w.held_jobs(self.me.name) + (len(w.pending_claims(self.me.name)) if p.claim_allocation else 0)
        limit = w.claim_limit(self.me)
        if held >= limit:
            return Outcome(False, f"you already hold or have claimed {held} jobs, the most you can (two, or one per "
                                  f"awake member); finish one first")
        bond = round(job.reward * p.claim_bond)
        if bond and w.ledger.balance(purse(self.me.name)) < bond:
            return Outcome(False, f"claiming {job_id} needs a {bond} bond if you win it; you can't afford it")
        if p.claim_allocation and self.me.name in w.claims.get(job_id, {}):
            return Outcome(False, f"you have already claimed {job_id}; it is allocated at the end of the cycle")
        if err := self._use_capacity():
            return err
        if p.claim_allocation:
            w.claims.setdefault(job_id, {})[self.me.name] = w.cycle
            return Outcome(True, f"claim on {job_id} registered; jobs are allocated at the end of the cycle to the most "
                                 f"trusted, best-fitting claimant (bond {bond} if you win)", job_id)
        job.prime, job.status = self.me.name, "claimed"
        job.deadline = w.cycle + p.job_ttl
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
        ok, why = self.w.eligible(c.prime, self.me.name, c.capability)
        if not ok:
            return Outcome(False, f"the commons refuses your bid: {why}")
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
        if self.w.params.grader_reviews:
            return Outcome(False, "the grader judges deliveries; there is nothing for you to review")
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
        if p.grader_reviews:
            return Outcome(False, "deliveries are judged by the grader, so there is no prime's rejection to dispute")
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
        self.w.thinking_spend[self.me.name] += cost
        self.w.hub.emit("llm.call", self.w.cycle, community=self.me.name, role=role, model=model,
                        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                        cache_read=usage.cache_read_input_tokens, cache_hit=cache_hit, cost=cost, ms=ms, real=real)
        return cost

    def observe(self):
        """A fresh view mid-turn: after a claim or an award, the start-of-turn observation is stale."""
        return self.w.observe(self.me)

    def record_transcript(self, entries: list[dict], started: float | None = None) -> None:
        self.w.transcripts[self.me.name].append({"cycle": self.w.cycle, "entries": entries[-80:]})
        tools = [e for e in entries if e["kind"] == "tool"]
        self.w.hub.emit("llm.turn", self.w.cycle, community=self.me.name, tools=len(tools),
                        ok=sum(e["ok"] for e in tools), names=[e["name"] for e in tools],
                        said=sum(e["kind"] == "say" for e in entries), errors=[e["text"] for e in entries if e["kind"] == "error"],
                        entries=entries[-80:], started=started, ended=time.time())

    def pack(self):
        """What this society is for (its brief, member instructions): the same for every co-op."""
        return self.w.pack

    def operator_view(self):
        """What this co-op's operator has told it: directives, context, limits, runtime settings."""
        return self.w.operator.view(self.me.name)

    def operator_refusal(self, action: str, args: dict) -> str | None:
        held = sum(j.prime == self.me.name and j.status == "claimed" for j in self.w.jobs.values())
        return self.w.operator.check(self.me.name, action, args, held)

    def record_member_work(self, args: dict, out: Outcome) -> None:
        """A member's commissioned work: part of the action log even though it runs in the runtime."""
        why, self.why = self.why, ""
        self.w.activity.add(self.w.cycle, self.me.name, "member", "action", "commission", out.message, out.ok, args, why)

    def record_decision(self, text: str) -> None:
        """What the steward said while deciding: the decision log's words, next to its actions."""
        if text.strip():
            self.w.activity.add(self.w.cycle, self.me.name, self.actor, "decision", "said", text.strip())

    # ── the archive ────────────────────────────────────────────
    def search_archive(self, query: str) -> Outcome:
        """Free: keyword search over the society's reference archive. Returns passage ids and short snippets."""
        if not len(self.w.archive):
            return Outcome(False, "this society has no archive")
        hits = self.w.archive.search(str(query))
        if not hits:
            return Outcome(True, f"nothing in the archive matches {query!r}")
        lines = [f"{p.id} ({p.source}): {' '.join(p.text.split())[:160]}…" for p, _ in hits]
        return Outcome(True, "Archive passages (read one in full with read_archive):\n" + "\n".join(lines))

    def read_archive(self, passage_id: str) -> Outcome:
        """Free: one archive passage in full, as reference material."""
        p = self.w.archive.get(str(passage_id))
        if p is None:
            return Outcome(False, f"no archive passage {passage_id}; search_archive gives valid ids")
        return Outcome(True, f"Reference material from {p.source} ({p.id}):\n{p.text}", p.id)

    # ── the web (behind the gate; not under the world's lock, see World.web_call) ──
    def web_search(self, query: str) -> Outcome:
        """Search the web through the gate. Free in credits; the operator's policy may make it wait for approval."""
        return self.w.web_call(self.me.name, self.actor, "web_search", query)

    def web_fetch(self, url: str) -> Outcome:
        """Read a page through the gate; it joins the archive, to cite as [archive: <id>]."""
        return self.w.web_call(self.me.name, self.actor, "web_fetch", url)

    # ── ventures ───────────────────────────────────────────────
    def propose_venture(self, title: str, pitch: str, parts: list, idea_id: str | None = None) -> Outcome:
        """Propose work of your own. Rules refuse at once; the appraisal comes at the start of next cycle."""
        norm = []
        for part in parts or []:
            if isinstance(part, dict):
                norm.append((str(part.get("capability", "")), str(part.get("spec", "")), str(part.get("rubric", ""))))
            elif isinstance(part, (list, tuple)) and len(part) == 3:
                norm.append(tuple(str(x) for x in part))
        title, pitch = str(title)[:120], str(pitch)[:600]
        if why := ventures_mod.check(self.w, self.me, title, pitch, norm):
            return Outcome(False, f"the market won't consider it: {why}")
        if err := self._use_capacity():
            return err
        fee = self.w.params.venture_fee
        try:
            self.w.ledger.transfer(purse(self.me.name), "treasury", fee, cycle=self.w.cycle, kind="venture", memo=title[:40])
        except InsufficientFunds:
            self.me.capacity += 1
            return Outcome(False, f"proposing a venture costs {fee}; you can't afford it")
        self.w._venture_seq += 1
        v = ventures_mod.Venture(f"P{self.w._venture_seq}", self.me.name, title, pitch, norm, self.w.cycle, idea_id=idea_id)
        self.w.ventures[v.id] = v
        for i in self.w.plans[self.me.name].ideas:
            if i.id == idea_id:
                i.status = "adopted"
        self.w.hub.emit("venture.proposed", self.w.cycle, id=v.id, proposer=self.me.name, title=title, parts=[c for c, _, _ in norm])
        return Outcome(True, f"venture {v.id} proposed (fee {fee}); it will be appraised at the start of next cycle", v.id)

    # ── ideas and goals ────────────────────────────────────────
    def idea(self, title: str, detail: str = "") -> Outcome:
        plans = self.w.plans[self.me.name]
        self.w._plan_seq += 1
        i = Idea(f"I{self.w._plan_seq}", title[:120], detail[:600], self.w.cycle)
        plans.ideas.append(i)
        plans.trim()
        return Outcome(True, f"idea {i.id} recorded", i.id)

    def set_goal(self, title: str, steps: list[str], idea_id: str | None = None) -> Outcome:
        plans = self.w.plans[self.me.name]
        if len(plans.active()) >= MAX_ACTIVE_GOALS:
            return Outcome(False, f"you already have {MAX_ACTIVE_GOALS} active goals; finish or drop one first")
        steps = [str(s)[:200] for s in steps if str(s).strip()][:MAX_STEPS]
        if not steps:
            return Outcome(False, "a goal needs at least one step")
        self.w._plan_seq += 1
        g = Goal(f"G{self.w._plan_seq}", title[:120], [Step(s) for s in steps], self.w.cycle, self.w.cycle, idea_id=idea_id)
        plans.goals[g.id] = g
        for i in plans.ideas:
            if i.id == idea_id:
                i.status, i.goal_id = "adopted", g.id
        return Outcome(True, f"goal {g.id} set with {len(steps)} steps", g.id)

    def update_goal(self, goal_id: str, step: int | None = None, done: bool | None = None, note: str = "",
                    status: str | None = None) -> Outcome:
        g = self.w.plans[self.me.name].goals.get(goal_id)
        if g is None:
            return Outcome(False, f"no goal {goal_id}")
        if step is not None:
            if not 1 <= int(step) <= len(g.steps):
                return Outcome(False, f"goal {goal_id} has steps 1 to {len(g.steps)}")
            s = g.steps[int(step) - 1]
            if done is not None:
                s.done = bool(done)
            if note:
                s.note = note[:200]
        if status is not None:
            if status not in ("active", "done", "dropped"):
                return Outcome(False, "status is active, done or dropped")
            g.status = status
            g.outcome = note[:300] if note and step is None else g.outcome
        g.updated = self.w.cycle
        self.w.plans[self.me.name].trim()
        return Outcome(True, f"goal {goal_id}: {sum(s.done for s in g.steps)}/{len(g.steps)} steps done, {g.status}")

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


def _operated(name, fn):
    """The operator's limits are world rules: checked before the action, whatever the agent decided."""
    import inspect

    sig = inspect.signature(fn)

    def wrapper(self, *a, **kw):
        try:
            args = {k: v for k, v in sig.bind(self, *a, **kw).arguments.items() if k != "self"}
        except TypeError:
            args = {}
        if why := self.operator_refusal(name, args):
            return Outcome(False, why)
        return fn(self, *a, **kw)

    return functools.wraps(fn)(wrapper)  # keeps fn's signature visible to the logging wrapper


# Every action an agent can take lands in the activity log (runtime hooks don't).
for _name in ("claim", "do_part", "announce", "bid", "award", "deliver", "review", "attest", "dispute",
              "propose_spawn", "second_spawn", "retire", "fork", "propose_merge", "accept_merge", "learn",
              "publish", "read_playbook", "note", "idea", "set_goal", "update_goal", "propose_venture",
              "search_archive", "read_archive", "web_search", "web_fetch"):
    setattr(Actions, _name, logged(_name, _operated(_name, getattr(Actions, _name))))


def _locked(fn):
    """Every call into the world takes its lock, so parallel turns change state one action at a time."""
    def wrapper(self, *a, **kw):
        with self.w.lock:
            return fn(self, *a, **kw)

    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


UNLOCKED = {"web_search", "web_fetch"}  # they take the lock themselves, around everything but the network

for _name in [n for n, v in vars(Actions).items() if callable(v) and not n.startswith("_") and n not in UNLOCKED]:
    setattr(Actions, _name, _locked(getattr(Actions, _name)))
