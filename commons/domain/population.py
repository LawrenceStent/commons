"""A population proposal: a spawn (add a member, needs a second from another co-op) or a merge (join another co-op,
needs its acceptance). The rules that act on them are in commons/application/population.py."""

from __future__ import annotations

from dataclasses import dataclass

from commons.domain.status import ProposalStatus


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
