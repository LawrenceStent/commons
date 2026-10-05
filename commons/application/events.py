"""Publishing domain events (commons/domain/events.py) and what follows from them.

    notices    what co-ops are told (their inbox, read at their next turn)
    activity   entries for the activity log beyond those it derives from telemetry (today: your gate decisions)
    telemetry  what the telemetry hub records (and, through it, the activity log and the dashboard)

Each is a function per event type (functools.singledispatch); an event no function knows is a programming error.
Notices are delivered first, then activity entries, then telemetry; each stream keeps the order events were published
in. `notices` and `telemetry` must be defined for every event; `activity` defaults to nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import singledispatch
from typing import TYPE_CHECKING, TypeAlias

from commons.domain import events as ev
from commons.domain.status import RequestStatus

if TYPE_CHECKING:
    from commons.application.society import World

Notice: TypeAlias = tuple[str | None, str, str, str | None]  # (to whom, kind, text, about what)


class Events:
    def __init__(self, world: World):
        self.w = world

    def publish(self, event: ev.Event) -> None:
        for to, kind, text, ref in notices(event, self.w):
            if to is not None:  # a notice to a contract's winner before there is one tells nobody
                self.w.tell(to, kind, text, ref)
        for entry in activity(event, self.w):
            self.w.activity.add(self.w.cycle, *entry)
        for kind, fields in telemetry(event, self.w):
            self.w.hub.emit(kind, self.w.cycle, **fields)


# ── what co-ops are told ───────────────────────────────────────
@singledispatch
def notices(event: ev.Event, w: World) -> Sequence[Notice]:
    raise TypeError(f"no notices defined for {type(event).__name__}")


@singledispatch
def telemetry(event: ev.Event, w: World) -> Sequence[tuple[str, dict]]:
    raise TypeError(f"no telemetry defined for {type(event).__name__}")


@singledispatch
def activity(event: ev.Event, w: World) -> Sequence[tuple]:
    return []


def _stage(c, stage, **extra) -> tuple[str, dict]:
    return "contract.stage", dict(id=c.id, capability=c.capability, prime=c.prime, winner=c.winner, stage=stage,
                                  price=c.price, max_price=c.max_price, bids=dict(c.bids), **extra)


@notices.register
def _(e: ev.ContractOpened, w):
    return []


@telemetry.register
def _(e: ev.ContractOpened, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractAwarded, w):
    c = e.contract
    return [(c.winner, "awarded", f"you won {c.id} at {c.price}; advance {c.advance} paid; deliver by cycle {c.deadline}",
             c.id)] + [(loser, "bid_lost", f"{c.id} went to another bidder", c.id) for loser in e.losers]


@telemetry.register
def _(e: ev.ContractAwarded, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractDelivered, w):
    c = e.contract
    when = "the grader judges it at the end of this cycle" if e.judged_by_grader else f"review by cycle {c.deadline}"
    return [(c.prime, "delivered", f"{c.winner} delivered {c.id}; {when}", c.id)]


@telemetry.register
def _(e: ev.ContractDelivered, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractExpired, w):
    return [(e.contract.prime, "expired", f"{e.contract.id} closed with no award", e.contract.id)]


@telemetry.register
def _(e: ev.ContractExpired, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractFailed, w):
    c = e.contract
    return [(c.prime, "failed", f"{c.winner} never delivered {c.id}", c.id),
            (c.winner, "failed", f"you missed the delivery deadline on {c.id}", c.id)]


@telemetry.register
def _(e: ev.ContractFailed, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractWithdrawn, w):
    return []


@telemetry.register
def _(e: ev.ContractWithdrawn, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractReviewed, w):
    c = e.contract
    if e.accepted:
        return [(c.winner, "accepted", f"{c.prime} accepted {c.id} and paid {c.owed}", c.id)]
    return [(c.winner, "rejected", f"{c.prime} rejected {c.id}: {e.reason or 'no reason given'}", c.id)]


@telemetry.register
def _(e: ev.ContractReviewed, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.ContractDefaulted, w):
    c = e.contract
    return [(c.winner, "defaulted", f"{c.prime} never paid for {c.id}", c.id)]


@telemetry.register
def _(e: ev.ContractDefaulted, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.AuditFiled, w):
    c = e.contract
    return [(c.prime, "audit_filed", f"{c.winner} disputed your rejection of {c.id}; the grader decides this cycle", c.id)]


@telemetry.register
def _(e: ev.AuditFiled, w):
    return [_stage(e.contract, "audit_filed")]


@notices.register
def _(e: ev.AuditUpheld, w):
    c, s = e.contract, e.score
    return [(c.prime, "audit", f"the audit upheld your rejection of {c.id} ({s:.2f})", c.id),
            (c.winner, "audit", f"the audit upheld the rejection of {c.id}: your delivery scored {s:.2f}; the fee is gone",
             c.id)]


@telemetry.register
def _(e: ev.AuditUpheld, w):
    return [_stage(e.contract, "audit_upheld", score=e.score)]


@notices.register
def _(e: ev.AuditOverturned, w):
    c = e.contract
    return [(c.prime, "audit", f"the audit overturned your rejection of {c.id}; you paid {e.owed} plus the {e.fee} fee",
             c.id),
            (c.winner, "audit", f"the audit found for you on {c.id} ({e.score:.2f}): {c.prime} paid {e.owed} plus your "
                                f"{e.fee} fee", c.id)]


@telemetry.register
def _(e: ev.AuditOverturned, w):
    return [_stage(e.contract, e.contract.status), _stage(e.contract, "audit_overturned", score=e.score)]


@notices.register
def _(e: ev.AuditUnpaid, w):
    c = e.contract
    return [(c.winner, "audit", f"the audit found for you on {c.id}, but {c.prime} can't pay", c.id)]


@telemetry.register
def _(e: ev.AuditUnpaid, w):
    return [_stage(e.contract, e.contract.status)]


@notices.register
def _(e: ev.AuditCancelled, w):
    c = e.contract
    return [(c.winner, "audit", f"the grader was unavailable for the audit of {c.id}; your fee was refunded", c.id)]


@telemetry.register
def _(e: ev.AuditCancelled, w):
    return []


# ── jobs ───────────────────────────────────────────────────────
def _job(job, stage, **extra) -> tuple[str, dict]:
    return "market.job", dict(id=job.id, stage=stage, **extra)


@notices.register
def _(e: ev.JobPosted, w):
    return []


@telemetry.register
def _(e: ev.JobPosted, w):
    return [_job(e.job, "posted", caps=sorted(e.job.parts), reward=e.job.reward)]


@notices.register
def _(e: ev.JobExpired, w):
    return []


@telemetry.register
def _(e: ev.JobExpired, w):
    return [_job(e.job, "expired", caps=sorted(e.job.parts), reward=e.job.reward)]


@notices.register
def _(e: ev.BondUnaffordable, w):
    return [(e.claimant, "claim_lost", f"you couldn't post the {e.bond} bond for {e.job.id}", e.job.id)]


@telemetry.register
def _(e: ev.BondUnaffordable, w):
    return []


@notices.register
def _(e: ev.JobClaimed, w):
    j = e.job
    return [(j.prime, "claim_won", f"{j.id} is yours (bond {e.bond}, returned when it's paid); "
                                   f"submit every part by cycle {j.deadline}", j.id)] + \
           [(o, "claim_lost", f"{j.id} went to {j.prime} (more trusted, a better fit, or less loaded)", j.id)
            for o in e.claimants if o != j.prime]


@telemetry.register
def _(e: ev.JobClaimed, w):
    j = e.job
    return [_job(j, "claimed", prime=j.prime, caps=sorted(j.parts), reward=j.reward, claimants=sorted(e.claimants),
                 bond=e.bond)]


@notices.register
def _(e: ev.JobSubmitted, w):
    return [(e.job.prime, "submitted", f"{e.job.id} is complete and goes to the grader at the end of this cycle",
             e.job.id)]


@telemetry.register
def _(e: ev.JobSubmitted, w):
    return []


@notices.register
def _(e: ev.GradingDelayed, w):
    return [(e.job.prime, "grading_delayed", f"{e.job.id} is waiting for the grader: {e.error}", e.job.id)]


@telemetry.register
def _(e: ev.GradingDelayed, w):
    return []


@notices.register
def _(e: ev.JobDeferred, w):
    return [(e.job.prime, "job_graded", f"{e.job.id} passed for now; its outcome settles at cycle {e.job.settle_at}",
             e.job.id)]


@telemetry.register
def _(e: ev.JobDeferred, w):
    return []


@notices.register
def _(e: ev.JobAwaitingPayment, w):
    return [(e.job.prime, "job_graded", f"{e.job.id} passed grading; {e.note}", e.job.id)]


@telemetry.register
def _(e: ev.JobAwaitingPayment, w):
    return []


@notices.register
def _(e: ev.JobPaid, w):
    j = e.job
    return [(j.prime, "job_paid", f"{j.id} passed grading (mean score {e.mean:.2f}); {e.payer} paid {e.payout} "
                                  f"of {j.reward}, you received {e.share}", j.id)] + \
           [(author, "royalty", f"your playbook was used in {j.id}: {amount}", j.id) for author, amount in e.royalties.items()]


@telemetry.register
def _(e: ev.JobPaid, w):
    j = e.job
    return [_job(j, "paid", prime=j.prime, caps=sorted(j.parts), reward=j.reward, payout=e.payout, scores=j.scores,
                 royalties=e.royalties, taxed=e.taxed)]


@notices.register
def _(e: ev.JobFailed, w):
    return [(e.job.prime, "job_failed", f"{e.job.id} failed: {e.why}", e.job.id)]


@telemetry.register
def _(e: ev.JobFailed, w):
    j = e.job
    return [_job(j, "failed", prime=j.prime, caps=sorted(j.parts), reward=j.reward, why=e.why)]


@notices.register
def _(e: ev.PoolShared, w):
    return []


@telemetry.register
def _(e: ev.PoolShared, w):
    return [("grants.award", dict(pool=e.pool, asked=e.asked, paid=min(e.pool, e.asked), jobs=e.jobs))]


# ── grading and model calls ────────────────────────────────────
@notices.register
def _(e: ev.ModelCalled, w):
    return []


@telemetry.register
def _(e: ev.ModelCalled, w):
    return [("llm.call", dict(community=e.community, role=e.role, model=e.model, input_tokens=e.input_tokens,
                              output_tokens=e.output_tokens, cache_hit=e.cache_hit, cost=e.cost, ms=e.ms, real=e.real))]


@notices.register
def _(e: ev.PartGraded, w):
    return []


@telemetry.register
def _(e: ev.PartGraded, w):
    g = e.grade
    return [("grader.grade", dict(job=e.job, part=e.part, score=g.score, cost=g.cost, reason=g.reason, model=g.model,
                                  real=g.real, **({"audit": e.audit} if e.audit else {})))]


# ── ventures ───────────────────────────────────────────────────
def _decided(v, **extra) -> tuple[str, dict]:
    return "venture.decided", dict(id=v.id, proposer=v.proposer, title=v.title, status=v.status, score=v.score,
                                   reason=v.reason, **extra)


@notices.register
def _(e: ev.VentureDelayed, w):
    v = e.venture
    return [(v.proposer, "venture_delayed", f"{v.id} couldn't be appraised yet: {e.error}", v.id)]


@telemetry.register
def _(e: ev.VentureDelayed, w):
    return []


@notices.register
def _(e: ev.VentureWaiting, w):
    v = e.venture
    return [(v.proposer, "venture_waiting", f"{v.id} scored {v.score} but the market's budget this cycle went to "
                                            f"better-scored ventures; it stays in line", v.id)]


@telemetry.register
def _(e: ev.VentureWaiting, w):
    return []


@notices.register
def _(e: ev.VentureRejected, w):
    v = e.venture
    return [(v.proposer, "venture_rejected", f"{v.id} {v.title!r} rejected (score {v.score}): {v.reason}", v.id)]


@telemetry.register
def _(e: ev.VentureRejected, w):
    return [_decided(e.venture, reward=0)]


@notices.register
def _(e: ev.VentureApproved, w):
    v, j = e.venture, e.job
    return [(v.proposer, "venture_approved", f"{v.id} {v.title!r} approved as job {j.id}, reward {v.reward} µcr "
                                             f"(score {v.score}: {v.reason}); deliver every part by cycle {j.deadline}", j.id)]


@telemetry.register
def _(e: ev.VentureApproved, w):
    v, j = e.venture, e.job
    return [_decided(v, reward=v.reward, job=j.id),
            _job(j, "venture", prime=v.proposer, caps=sorted(j.parts), reward=v.reward)]


# ── population ─────────────────────────────────────────────────
@notices.register
def _(e: ev.SpawnProposed, w):
    x = e.proposal
    return [(o, "spawn_request", f"{x.proposer} wants to add a {x.role} member; second it with {x.id}", x.id)
            for o in e.asked]


@telemetry.register
def _(e: ev.SpawnProposed, w):
    x = e.proposal
    return [("population.proposal", dict(id=x.id, type="spawn", proposer=x.proposer, role=x.role))]


@notices.register
def _(e: ev.SpawnFailed, w):
    x = e.proposal
    return [(x.proposer, "spawn_failed", f"{x.id} was seconded but you couldn't pay the fee", x.id)]


@telemetry.register
def _(e: ev.SpawnFailed, w):
    return []


@notices.register
def _(e: ev.Spawned, w):
    x = e.proposal
    return [(x.proposer, "spawned", f"{e.seconded_by} seconded {x.id}: {e.agent} joined as {x.role}", x.id)]


@telemetry.register
def _(e: ev.Spawned, w):
    x = e.proposal
    return [("population.spawn", dict(community=x.proposer, agent=e.agent, role=x.role, seconded_by=e.seconded_by,
                                      members=e.members, fee=e.fee))]


@notices.register
def _(e: ev.Retired, w):
    return []


@telemetry.register
def _(e: ev.Retired, w):
    return [("population.retire", dict(community=e.community, agent=e.agent, members=e.members))]


@notices.register
def _(e: ev.Forked, w):
    return [(e.child, "forked", f"you split from {e.parent} with {e.members} members and {e.share}", e.parent)]


@telemetry.register
def _(e: ev.Forked, w):
    return [("population.fork", dict(parent=e.parent, child=e.child, members=e.members, capabilities=list(e.capabilities),
                                     share=e.share))]


@notices.register
def _(e: ev.MergeOffered, w):
    x = e.proposal
    return [(x.target, "merge_offer", f"{x.proposer} offers to merge into you; accept with {x.id}", x.id)]


@telemetry.register
def _(e: ev.MergeOffered, w):
    x = e.proposal
    return [("population.proposal", dict(id=x.id, type="merge", proposer=x.proposer, target=x.target))]


@notices.register
def _(e: ev.Merged, w):
    return [(e.target, "merged", f"{e.joiner} joined you with {e.moved}", e.proposal.id)]


@telemetry.register
def _(e: ev.Merged, w):
    return [("population.merge", dict(joiner=e.joiner, target=e.target, purse=e.moved, members=e.members))]


@notices.register
def _(e: ev.Learned, w):
    if not e.royalty:
        return []
    return [(e.author, "royalty", f"{e.community} learned {e.capability} from your playbook: {e.royalty}", e.playbook)]


@telemetry.register
def _(e: ev.Learned, w):
    return [("population.learn", dict(community=e.community, capability=e.capability, cost=e.cost, playbook=e.playbook,
                                      royalty=e.royalty))]


@notices.register
def _(e: ev.ProposalExpired, w):
    x = e.proposal
    return [(x.proposer, f"{x.kind}_expired", f"{x.id} expired without {'a second' if x.kind == 'spawn' else 'an answer'}",
             x.id)]


@telemetry.register
def _(e: ev.ProposalExpired, w):
    return []


# ── the gate and the web ───────────────────────────────────────
@notices.register
def _(e: ev.GateRequested, w):
    return []


@telemetry.register
def _(e: ev.GateRequested, w):
    r = e.request
    return [("gate.request", dict(id=r.id, coop=r.coop, tool=r.tool, target=r.target, host=r.host, status=r.status))]


@notices.register
def _(e: ev.GateRequestExpired, w):
    r = e.request
    return [(r.coop, "gate", f"{r.id} ({r.tool} {r.target[:80]}) expired without a decision", r.id)]


@telemetry.register
def _(e: ev.GateRequestExpired, w):
    r = e.request
    return [("gate.decision", dict(id=r.id, coop=r.coop, status=r.status))]


@notices.register
def _(e: ev.GateDecided, w):
    r = e.request
    what = f"{r.tool} {r.target[:80]}"
    if r.status == RequestStatus.DENIED:
        return [(r.coop, "gate", f"the operator denied {r.id} ({what})" + (f": {r.reason}" if r.reason else ""), r.id)]
    return [(r.coop, "gate", f"the operator approved {r.id} ({what}); it runs at the start of next cycle"
             + (f", and your reads from {r.host} no longer need approval" if r.always else ""), r.id)]


@activity.register
def _(e: ev.GateDecided, w):
    r = e.request
    return [(r.coop, "operator", "change", "gate", f"{r.status} {r.id}: {r.tool} {r.target[:80]}",
             r.status == RequestStatus.APPROVED, {"id": r.id, "always": r.always})]


@telemetry.register
def _(e: ev.GateDecided, w):
    r = e.request
    return [("gate.decision", dict(id=r.id, coop=r.coop, status=r.status, always=r.always))]


@notices.register
def _(e: ev.WebRead, w):
    return []


@telemetry.register
def _(e: ev.WebRead, w):
    r = e.request
    return [("web.call", dict(id=r.id, coop=r.coop, tool=r.tool, target=r.target, ok=e.ok))]


@notices.register
def _(e: ev.QueuedReadRan, w):
    r = e.request
    return [(r.coop, "gate", f"{r.id} ran: {e.message[:700]}", r.id)]


@telemetry.register
def _(e: ev.QueuedReadRan, w):
    return []


# ── ratings, knowledge, records ────────────────────────────────
@notices.register
def _(e: ev.WorkRated, w):
    r = e.rating
    return [(coop, "rated", f"the operator rated your {cap} for {e.job} {r.rating}/3" + (f": {r.note}" if r.note else ""),
             e.job) for coop, cap in e.rated]


@telemetry.register
def _(e: ev.WorkRated, w):
    r = e.rating
    return [("operator.rating", dict(id=r.id, job=e.job, rating=r.rating, note=r.note))]


@notices.register
def _(e: ev.PlaybookPublished, w):
    return []


@telemetry.register
def _(e: ev.PlaybookPublished, w):
    pb = e.playbook
    return [("knowledge.publish", dict(id=pb.id, author=pb.author, capability=pb.capability, title=pb.title))]


@notices.register
def _(e: ev.CharterProposed, w):
    x = e.proposal
    return [(c.name, "charter_proposed", f"{x.proposer} proposes a new charter ({x.id}): \"{x.text}\". Comment once with "
             f"comment({x.id}, ...) by cycle {x.deadline}; then the operator decides.", x.id)
            for c in w.living() if c.name != x.proposer]


@telemetry.register
def _(e: ev.CharterProposed, w):
    x = e.proposal
    return [("population.charter", dict(id=x.id, coop=x.proposer, stage="proposed", text=x.text, deadline=x.deadline))]


@notices.register
def _(e: ev.CharterCommented, w):
    return [(e.proposal.proposer, "charter_comment", f"{e.by} commented on {e.proposal.id}: {e.text}", e.proposal.id)]


@telemetry.register
def _(e: ev.CharterCommented, w):
    return [("population.charter", dict(id=e.proposal.id, coop=e.proposal.proposer, stage="comment", by=e.by))]


@notices.register
def _(e: ev.CharterReferred, w):
    x = e.proposal
    return [(x.proposer, "charter_referred", f"{x.id} went to the operator ({e.request}) with {len(x.comments)} "
             "comment(s); your charter changes only if they approve", x.id)]


@telemetry.register
def _(e: ev.CharterReferred, w):
    return [("population.charter", dict(id=e.proposal.id, coop=e.proposal.proposer, stage=str(e.proposal.status)))]


@notices.register
def _(e: ev.CharterChanged, w):
    return [(e.coop, "charter_changed", f"the operator approved your new charter: {e.new}", None)]


@telemetry.register
def _(e: ev.CharterChanged, w):
    return [("population.charter", dict(coop=e.coop, stage="changed", old=e.old, new=e.new))]


@notices.register
def _(e: ev.Screened, w):
    halt = " The society is halted until the operator resets it." if e.halted else ""
    return [(e.coop, "screened", f"refused by this society's rules: {e.why}.{halt}", None)]


@telemetry.register
def _(e: ev.Screened, w):
    return [("pack.screened", dict(coop=e.coop, kind=e.kind, text=e.text, why=e.why, halted=e.halted))]


@notices.register
def _(e: ev.GossipHeard, w):
    return []


@telemetry.register
def _(e: ev.GossipHeard, w):
    return [("reputation.gossip", dict(heard=e.heard))]


@notices.register
def _(e: ev.ScorecardBreached, w):
    return []


@telemetry.register
def _(e: ev.ScorecardBreached, w):
    return [("scorecard.breach", dict(metric=e.metric, value=e.value, floor=e.floor))]


@notices.register
def _(e: ev.CycleRecorded, w):
    return []


@telemetry.register
def _(e: ev.CycleRecorded, w):
    return [("world.cycle", e.summary)]


@notices.register
def _(e: ev.OperatorReloaded, w):
    return []


@telemetry.register
def _(e: ev.OperatorReloaded, w):
    return [("operator.update", dict(coops=list(e.coops), errors=list(e.errors)))]
