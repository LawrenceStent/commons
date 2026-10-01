"""Population and capability changes: spawn, retire, fork, merge, learn.

These change who exists and what they can do, so each has a check that stops one community
doing it alone or cheaply:

    spawn   adds a member. Costs a fee to the treasury and needs a second from a *different*
            community within `spawn_window` cycles, so no one grows unilaterally.
    retire  drops a member. No refund.
    fork    some members walk out as a new community with a pro-rata share of what the purse
            holds beyond its debts, and some of the parent's capabilities. It inherits the parent's
            reputation with good evidence discounted and bad evidence kept in full, so forking
            can't wash a record clean.
    merge   both sides agree. The joining community must have nothing in flight; its members,
            purse, capabilities and playbooks move to the target, and it dissolves.
    learn   buys a capability: the third costs `learn_cost`, the fourth twice that, and so on,
            so generalists pay for it. Cheaper when building on a playbook, whose author earns a royalty.

Every function returns an Outcome; the actions executor is the only caller.
"""

from __future__ import annotations

import copy
import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.domain.community import Community
from commons.domain.ids import PlaybookId
from commons.domain.status import ContractStatus, JobStatus, ProposalStatus
from commons.protocol.population import Fork, Merge, Retire, Spawn
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.world import World

NAME = re.compile(r"^[a-z][a-z0-9-]{1,23}$")


@dataclass
class Proposal:
    id: str
    kind: str  # spawn | merge
    proposer: str
    cycle: int
    deadline: int
    role: str = ""
    target: str = ""  # merge: who is asked to absorb the proposer
    status: ProposalStatus = ProposalStatus.OPEN


def _live(w: World, name: str) -> bool:
    """Anything in flight that `name` owes or is owed."""
    if any(j.prime == name and j.status == JobStatus.CLAIMED for j in w.jobs.values()):
        return True
    return any(name in (c.prime, c.winner) and c.status in (ContractStatus.OPEN, ContractStatus.AWARDED, ContractStatus.DELIVERED) for c in w.contracts.values())


def _new_id(w: World, kind: str) -> str:
    return f"{kind[0].upper()}{w.ids.next('proposal')}"


# ── spawn / retire ─────────────────────────────────────────────
def propose_spawn(w: World, me: Community, role: str) -> Outcome:
    p = w.params
    if me.members >= p.max_members:
        return Outcome(False, f"you already have {me.members} members, the most a community can have; fork instead")
    if any(x.proposer == me.name and x.kind == "spawn" and x.status == ProposalStatus.OPEN for x in w.proposals.values()):
        return Outcome(False, "you already have a spawn waiting for a second")
    if w.ledger.balance(purse(me.name)) < p.spawn_fee:
        return Outcome(False, f"a spawn costs {p.spawn_fee}; you can't afford it")
    pid = _new_id(w, "spawn")
    w.proposals[pid] = Proposal(pid, "spawn", me.name, w.cycle, w.cycle + p.spawn_window, role=role[:60])
    for other in w.communities.values():
        if other.name != me.name and not other.dissolved:
            w.tell(other.name, "spawn_request", f"{me.name} wants to add a {role[:60]} member; second it with {pid}", pid)
    w.hub.emit("population.proposal", w.cycle, id=pid, type="spawn", proposer=me.name, role=role[:60])
    return Outcome(True, f"proposed {pid}; it needs a second from another community by cycle {w.proposals[pid].deadline}", pid)


def second_spawn(w: World, me: Community, pid: str) -> Outcome:
    x = w.proposals.get(pid)
    if x is None or x.kind != "spawn" or x.status != ProposalStatus.OPEN:
        return Outcome(False, f"no open spawn proposal {pid}")
    if x.proposer == me.name:
        return Outcome(False, "a spawn needs a second from a different community")
    prop = w.communities[x.proposer]
    if prop.members >= w.params.max_members:
        x.status = ProposalStatus.FAILED
        return Outcome(False, f"{prop.name} is already at the member limit")
    try:
        w.ledger.transfer(purse(prop.name), "treasury", w.params.spawn_fee, cycle=w.cycle, kind="spawn", memo=pid)
    except InsufficientFunds:
        x.status = ProposalStatus.FAILED
        w.tell(prop.name, "spawn_failed", f"{pid} was seconded but you couldn't pay the fee", pid)
        return Outcome(False, f"{prop.name} can no longer pay the spawn fee")
    prop.members += 1
    x.status = ProposalStatus.DONE
    agent = f"{prop.name}#{prop.members}"
    w.send(prop, Spawn(agent=agent, role=x.role, seconded_by=me.name))
    w.tell(prop.name, "spawned", f"{me.name} seconded {pid}: {agent} joined as {x.role}", pid)
    w.hub.emit("population.spawn", w.cycle, community=prop.name, agent=agent, role=x.role, seconded_by=me.name,
               members=prop.members, fee=w.params.spawn_fee)
    return Outcome(True, f"seconded {pid}; {prop.name} now has {prop.members} members")


def retire(w: World, me: Community) -> Outcome:
    if me.members <= 1:
        return Outcome(False, "a community keeps at least one member; merge or go quiet instead")
    agent = f"{me.name}#{me.members}"
    me.members -= 1
    w.send(me, Retire(agent=agent))
    w.hub.emit("population.retire", w.cycle, community=me.name, agent=agent, members=me.members)
    return Outcome(True, f"{agent} retired; {me.members} members remain")


# ── fork ───────────────────────────────────────────────────────
def fork(w: World, me: Community, name: str, members: int, capabilities: tuple[str, ...], charter: str) -> Outcome:
    p = w.params
    if not NAME.match(name or ""):
        return Outcome(False, "a community name is 2-24 characters: lowercase letters, digits and hyphens, starting with a letter")
    if name in w.communities:
        return Outcome(False, f"{name} already exists")
    if sum(not c.dissolved for c in w.communities.values()) >= p.max_communities:
        return Outcome(False, f"the commons is at its limit of {p.max_communities} communities")
    if not 1 <= members < me.members:
        return Outcome(False, f"a fork takes between 1 and {me.members - 1} members; someone has to stay")
    caps = tuple(sorted(set(capabilities)))
    if not caps or not set(caps) <= me.capabilities:
        return Outcome(False, "a fork takes a non-empty subset of your capabilities")
    owed = sum(c.owed for c in w.contracts.values() if c.prime == me.name and c.status in (ContractStatus.AWARDED, ContractStatus.DELIVERED))
    share = max(0, w.ledger.balance(purse(me.name)) - owed) * members // me.members

    child = Community(name, members, set(caps), copy.deepcopy(me.strategy), charter=charter[:200] or me.charter,
                      parent=me.name)
    child.strategy.rng = random.Random(f"{p.seed}:{name}")
    w.add_community(child)
    if share:
        w.ledger.transfer(purse(me.name), purse(name), share, cycle=w.cycle, kind="fork", memo=f"{me.name} -> {name}")
    me.members -= members
    w.rep.inherit(me.name, name, caps, good=p.fork_good_keep, bad=1.0)
    w.send(me, Fork(new_community=name, members=[f"{name}#{i + 1}" for i in range(members)]))
    w.tell(name, "forked", f"you split from {me.name} with {members} members and {share}", me.name)
    w.hub.emit("population.fork", w.cycle, parent=me.name, child=name, members=members, capabilities=list(caps), share=share)
    return Outcome(True, f"{name} forked with {members} members, {', '.join(caps)}, and {share}; {me.members} members stay", name)


# ── merge ──────────────────────────────────────────────────────
def propose_merge(w: World, me: Community, target: str) -> Outcome:
    t = w.communities.get(target)
    if t is None or t.dissolved or t.name == me.name:
        return Outcome(False, f"no community {target} to merge into")
    pid = _new_id(w, "merge")
    w.proposals[pid] = Proposal(pid, "merge", me.name, w.cycle, w.cycle + w.params.merge_window, target=target)
    w.tell(target, "merge_offer", f"{me.name} offers to merge into you; accept with {pid}", pid)
    w.hub.emit("population.proposal", w.cycle, id=pid, type="merge", proposer=me.name, target=target)
    return Outcome(True, f"offered to merge into {target}; they have until cycle {w.proposals[pid].deadline}", pid)


def accept_merge(w: World, me: Community, pid: str) -> Outcome:
    x = w.proposals.get(pid)
    if x is None or x.kind != "merge" or x.status != ProposalStatus.OPEN or x.target != me.name:
        return Outcome(False, f"no open merge offer {pid} addressed to you")
    joiner = w.communities[x.proposer]
    if joiner.dissolved:
        x.status = ProposalStatus.FAILED
        return Outcome(False, f"{joiner.name} no longer exists")
    if _live(w, joiner.name):
        return Outcome(False, f"{joiner.name} still has jobs or contracts in flight; it can join once they close")
    if me.members + joiner.members > w.params.max_members:
        return Outcome(False, f"together you'd have {me.members + joiner.members} members, over the limit of {w.params.max_members}")
    moved = w.ledger.balance(purse(joiner.name))
    if moved:
        w.ledger.transfer(purse(joiner.name), purse(me.name), moved, cycle=w.cycle, kind="merge", memo=pid)
    me.members += joiner.members
    me.capabilities = frozenset(me.capabilities | joiner.capabilities)
    for pb in w.library.values():
        if pb.author == joiner.name:
            pb.author = me.name  # royalties follow the members who wrote it
    w.send(joiner, Merge(target=me.name))
    joiner.members, joiner.dissolved, joiner.active = 0, True, False
    w.registry.register(me.name, me.identity.public, sorted(me.capabilities), me.charter)
    x.status = ProposalStatus.DONE
    w.tell(me.name, "merged", f"{joiner.name} joined you with {moved}", pid)
    w.hub.emit("population.merge", w.cycle, joiner=joiner.name, target=me.name, purse=moved, members=me.members)
    return Outcome(True, f"{joiner.name} merged into you; you now have {me.members} members")


# ── learn ──────────────────────────────────────────────────────
def learn(w: World, me: Community, capability: str, playbook_id: PlaybookId | None = None) -> Outcome:
    p = w.params
    if capability in me.capabilities:
        return Outcome(False, f"you already have {capability}")
    if capability not in w.known_capabilities:
        return Outcome(False, f"{capability} isn't a capability anyone trades: {', '.join(sorted(w.known_capabilities))}")
    pb = w.library.get(playbook_id) if playbook_id else None
    if playbook_id and (pb is None or pb.capability != capability):
        return Outcome(False, f"{playbook_id} isn't a {capability} playbook")
    # each capability beyond the second costs twice the last: specialists are cheap, generalists aren't
    base = p.learn_cost * 2 ** max(0, len(me.capabilities) - 2)
    cost = round(base * (1 - p.learn_playbook_discount)) if pb else base
    royalty = round(p.learn_cost * p.learn_royalty) if pb and pb.author != me.name else 0
    if w.ledger.balance(purse(me.name)) < cost + royalty:
        return Outcome(False, f"learning {capability} costs {cost + royalty}; you can't afford it")
    w.meter.charge(me.name, cost, cycle=w.cycle, memo=f"learn {capability}")
    if royalty:
        w.ledger.transfer(purse(me.name), purse(pb.author), royalty, cycle=w.cycle, kind="royalty", memo=f"learn {pb.id}")
        pb.uses += 1
        w.royalties_paid[pb.author] = w.royalties_paid.get(pb.author, 0) + royalty
        w.tell(pb.author, "royalty", f"{me.name} learned {capability} from your playbook: {royalty}", pb.id)
    me.capabilities = frozenset(me.capabilities | {capability})
    w.registry.register(me.name, me.identity.public, sorted(me.capabilities), me.charter)
    w.hub.emit("population.learn", w.cycle, community=me.name, capability=capability, cost=cost, playbook=playbook_id, royalty=royalty)
    via = f" using {pb.id}" if pb else ""
    return Outcome(True, f"learned {capability}{via} for {cost + royalty}; your record in it starts neutral")


def expire_proposals(w: World) -> None:
    for x in w.proposals.values():
        if x.status == ProposalStatus.OPEN and w.cycle > x.deadline:
            x.status = ProposalStatus.EXPIRED
            w.tell(x.proposer, f"{x.kind}_expired", f"{x.id} expired without {'a second' if x.kind == 'spawn' else 'an answer'}", x.id)
    for k in [k for k, x in w.proposals.items() if x.status != ProposalStatus.OPEN and x.deadline < w.cycle - w.params.retain]:
        del w.proposals[k]


__all__ = ["Proposal", "propose_spawn", "second_spawn", "retire", "fork", "propose_merge", "accept_merge", "learn",
           "expire_proposals"]
