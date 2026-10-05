"""A population proposal: a spawn (add a member, needs a second from another co-op), a merge (join another co-op,
needs its acceptance), or a charter change (a request for comment: other co-ops comment for a while, then it goes to
the operator's gate). The rules that act on them are in commons/application/population.py and charters.py."""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.status import ProposalStatus


@dataclass
class Proposal:
    id: str
    kind: str  # spawn | merge | charter
    proposer: str
    cycle: int
    deadline: int
    role: str = ""  # spawn: the new member's role; charter: why
    target: str = ""  # merge: who is asked to absorb the proposer
    status: ProposalStatus = ProposalStatus.OPEN
    text: str = ""  # charter: the proposed charter
    comments: dict[str, str] = field(default_factory=dict)  # charter: co-op -> its comment
