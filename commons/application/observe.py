"""What a co-op sees at the start of its turn: the board, its jobs and contracts, open contracts it could bid on, its
events, peers, the library, proposals, ventures, ideas and goals, its operator's limits, and what the world allows it.
A read model: building an observation changes nothing."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from commons.application.observation import (
    BidView,
    ContractView,
    GoalView,
    IdeaView,
    JobView,
    Observation,
    PartView,
    PeerView,
    PlaybookView,
    ProposalView,
    VentureView,
)
from commons.domain.community import Community
from commons.domain.contract import Contract
from commons.domain.market import MarketJob
from commons.domain.status import (
    LIVE_CONTRACT,
    ContractStatus,
    JobStatus,
    ProposalStatus,
)
from commons.substrate.ledger import purse

if TYPE_CHECKING:
    from commons.application.society import World


class ObservationBuilder:
    def __init__(self, world: World):
        self.w = world

    def build(self, me: Community) -> Observation:
        return Observation(**self._own(me), **self._work(me), **self._neighbours(me), **self._plans(me),
                           **self._surroundings(me))

    # ── views ──────────────────────────────────────────────────
    def _job_view(self, j: MarketJob, pending: dict) -> JobView:
        return JobView(j.id, j.title, j.reward, tuple(
            PartView(cap, part.spec, part.rubric, part.artifact is not None, part.source, pending.get((j.id, cap)))
            for cap, part in sorted(j.parts.items())), j.deadline)

    def _contract_view(self, name: str, c: Contract, as_prime: bool) -> ContractView:
        bids = tuple(BidView(b, price, round(self.w.trust(name, b, c.capability), 3), round(self.w.standing(b), 3),
                             *self.w.eligible(name, b, c.capability))
                     for b, price in sorted(c.bids.items())) if as_prime else ()
        show = as_prime and c.status != ContractStatus.OPEN or c.winner == name
        return ContractView(c.id, c.job_id, c.capability, c.prime, c.spec, c.rubric, c.max_price, c.advance_frac,
                            c.announced, bids, c.bids.get(name), c.winner, c.price,
                            c.artifact if show else None, c.deadline, c.status)

    # ── sections ───────────────────────────────────────────────
    def _own(self, me: Community) -> dict:
        """The co-op itself."""
        name = me.name
        return dict(cycle=self.w.cycle, name=name, charter=me.charter, capabilities=tuple(sorted(me.capabilities)),
                    members=me.members, funded=me.thinking, capacity=me.capacity,
                    purse=self.w.ledger.balance(purse(name)), standing=round(self.w.standing(name), 3),
                    claim_limit=max(2, me.thinking), track=dict(me.deliveries), doctrine=me.doctrine,
                    efficiency=self.w.recorder.efficiency(name), events=tuple(self.w.inbox[name]),
                    journal=tuple(self.w.journal[name]))

    def _work(self, me: Community) -> dict:
        """Jobs and contracts: the board, its own work, and what it may bid on, deliver, review, rate or dispute."""
        name, p, cs = me.name, self.w.params, self.w.contracts.values()
        pending = {(c.job_id, c.capability): c.status for c in cs if c.status in LIVE_CONTRACT}
        view = partial(self._contract_view, name)
        closed = (ContractStatus.ACCEPTED, ContractStatus.REJECTED, ContractStatus.FAILED)
        return dict(
            board=tuple(self._job_view(j, pending) for j in self.w.jobs.values() if j.status == JobStatus.OPEN),
            my_jobs=tuple(self._job_view(j, pending) for j in self.w.jobs.values()
                          if j.status == JobStatus.CLAIMED and j.prime == name),
            # a world rule: contracts the commons would refuse my bid on aren't offered at all
            open_contracts=tuple(view(c, False) for c in cs if c.status == ContractStatus.OPEN and c.prime != name
                                 and self.w.eligible(c.prime, name, c.capability)[0]),
            refused_contracts=sum(1 for c in cs if c.status == ContractStatus.OPEN and c.prime != name
                                  and c.capability in me.capabilities and not self.w.eligible(c.prime, name, c.capability)[0]),
            my_announcements=tuple(view(c, True) for c in cs if c.status == ContractStatus.OPEN and c.prime == name),
            to_deliver=tuple(view(c, False) for c in cs if c.status == ContractStatus.AWARDED and c.winner == name),
            to_review=tuple(view(c, True) for c in cs if c.status == ContractStatus.DELIVERED and c.prime == name
                            and not p.grader_reviews),
            to_attest=tuple(view(c, False) for c in cs if c.winner == name and c.closed is not None
                            and c.status in closed and not c.winner_attested),
            to_dispute=tuple(view(c, False) for c in cs if not p.grader_reviews and c.winner == name
                             and c.status == ContractStatus.REJECTED and not c.disputed
                             and self.w.cycle <= c.closed + p.dispute_window),
            owed=sum(c.owed for c in cs if c.prime == name and c.status in (ContractStatus.AWARDED, ContractStatus.DELIVERED)),
            pending_claims=tuple(self.w.board.pending_claims(name)),
        )

    def _neighbours(self, me: Community) -> dict:
        """The other co-ops, their proposals, and the shared library."""
        name, standing = me.name, self.w.standing
        open_ = [x for x in self.w.proposals.values() if x.status == ProposalStatus.OPEN]
        return dict(
            peers=tuple(PeerView(o.name, tuple(sorted(o.capabilities)), o.members, round(standing(o.name), 3),
                                 {cap: round(self.w.trust(name, o.name, cap), 3) for cap in sorted(o.capabilities)})
                        for o in self.w.living() if o.name != name),
            spawn_requests=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role, round(standing(x.proposer), 3))
                                 for x in open_ if x.kind == "spawn" and x.proposer != name),
            merge_offers=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, "", round(standing(x.proposer), 3))
                               for x in open_ if x.kind == "merge" and x.target == name),
            my_proposals=tuple(ProposalView(x.id, x.kind, x.proposer, x.deadline, x.role or x.target, 0.0)
                               for x in open_ if x.proposer == name),
            library=tuple(PlaybookView(pb.id, pb.capability, pb.author, pb.title, pb.uses) for pb in self.w.library.values()),
        )

    def _plans(self, me: Community) -> dict:
        """Its ventures, goals and ideas."""
        plans = self.w.plans[me.name]
        return dict(
            ventures=tuple(VentureView(v.id, v.title, v.status, v.score, v.reward, v.reason, v.job_id, v.cycle)
                           for v in list(self.w.ventures.values()) if v.proposer == me.name)[-5:],
            goals=tuple(GoalView(g.id, g.title, g.status, tuple((s.text, s.done, s.note) for s in g.steps), round(g.progress, 2))
                        for g in plans.active()),
            ideas=tuple(IdeaView(i.id, i.title, i.detail, i.cycle, i.status) for i in plans.ideas[-5:]),
        )

    def _surroundings(self, me: Community) -> dict:
        """What the world offers: its rules' numbers, the archive, the economy's pool, the web."""
        p = self.w.params
        return dict(
            params={"sub_share": p.sub_share, "work_cost": p.work_cost, "advance_frac": p.advance_frac,
                    "publish_cost": p.publish_cost, "spawn_fee": p.spawn_fee, "venture_fee": p.venture_fee,
                    "learn_cost": p.learn_cost, "audit_cost": p.audit_cost, "max_members": p.max_members,
                    "pass_score": p.pass_score, "max_communities": p.max_communities,
                    "communities": len(self.w.living()), "upkeep": p.upkeep,
                    "actions_per_member": p.actions_per_member, "job_ttl": p.job_ttl},
            archive=(len(self.w.archive), tuple(sorted({x.source for x in self.w.archive.passages.values()}))),
            grants=self.w.payment.view(self.w.payments.pool_balance()),
            web=self.w.gate.policy.describe() if self.w.web else "",
        )
