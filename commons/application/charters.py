"""Charter changes (Phase 2; your decision, 5 Oct): a co-op can't change its own charter. It files a request for
comment; every other living co-op is told and may comment once, for `charter_window` cycles; then the proposal, with
every comment, goes to your gate as a "govern" request. Only your approval changes the charter (and the co-op's card
in the registry). The pack's screen reads the proposed charter first, as it reads a brief.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.application.screening import screen
from commons.application.services.approvals import CARRIERS
from commons.domain import events as ev
from commons.domain.population import Proposal
from commons.domain.status import ProposalStatus

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.community import Community
    from commons.domain.gate import Request

MIN, MAX = 20, 400  # characters of charter


def propose(w: World, me: Community, text: str, reason: str) -> Outcome:
    text, reason = " ".join(str(text).split()), " ".join(str(reason).split())[:300]
    if not MIN <= len(text) <= MAX:
        return Outcome(False, f"a charter is {MIN} to {MAX} characters")
    if text == me.charter:
        return Outcome(False, "that is already your charter")
    if any(x.kind == "charter" and x.proposer == me.name and x.status in (ProposalStatus.OPEN, ProposalStatus.REFERRED)
           for x in w.proposals.values()):
        return Outcome(False, "you already have a charter change in progress")
    if why := screen(w, me.name, "brief", text):
        return Outcome(False, why)
    p = w.params.population
    pid = f"R{w.ids.next('proposal')}"
    x = Proposal(pid, "charter", me.name, w.cycle, w.cycle + p.charter_window, role=reason, text=text)
    w.proposals[pid] = x
    w.events.publish(ev.CharterProposed(x))
    return Outcome(True, f"charter change {pid} proposed: other co-ops may comment until cycle {x.deadline}, then it "
                         "goes to the operator", pid)


def comment(w: World, me: Community, proposal_id: str, text: str) -> Outcome:
    x = w.proposals.get(str(proposal_id))
    if x is None or x.kind != "charter" or x.status != ProposalStatus.OPEN:
        return Outcome(False, f"no charter change {proposal_id} open for comment")
    if x.proposer == me.name:
        return Outcome(False, "you can't comment on your own charter change")
    if me.name in x.comments:
        return Outcome(False, "you have already commented on it")
    text = " ".join(str(text).split())[:500]
    if not text:
        return Outcome(False, "say something")
    x.comments[me.name] = text
    w.events.publish(ev.CharterCommented(x, me.name, text))
    return Outcome(True, f"commented on {x.id}")


def refer(w: World, x: Proposal) -> None:
    """The comment window is over: to your gate, with every comment. Under the lock."""
    comments = "\n".join(f"- {who}: {said}" for who, said in sorted(x.comments.items())) or "- none"
    detail = (f"{x.proposer} asks to change its charter.\nNow: {w.communities[x.proposer].charter}\nProposed: {x.text}\n"
              f"Why: {x.role or '-'}\nComments from other co-ops:\n{comments}")
    out = w.approvals.request(x.proposer, "rule", "change_charter", "govern", x.id, detail)
    x.status = ProposalStatus.REFERRED if out.ok else ProposalStatus.FAILED
    w.events.publish(ev.CharterReferred(x, out.id or out.message))


def carry_out(w: World, r: Request) -> tuple[bool, str]:
    """You approved it: the charter changes, and the co-op's card in the registry with it."""
    with w.lock:
        x = w.proposals.get(r.target)
        c = w.communities.get(x.proposer) if x else None
        if x is None or c is None or c.dissolved:
            return False, f"charter change {r.target} no longer applies"
        old, c.charter, x.status = c.charter, x.text, ProposalStatus.DONE
        w.registry.register(c.name, c.identity.public, sorted(c.capabilities), c.charter)
        w.events.publish(ev.CharterChanged(c.name, old, c.charter))
    return True, f"{c.name}'s charter is now: {c.charter}"


CARRIERS["change_charter"] = carry_out
