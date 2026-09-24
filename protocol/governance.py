"""Governance: propose · second · vote · enact. Schemas only until Phase 1."""

from typing import Any, Literal

from protocol.envelope import Message, message


@message("governance", "propose")
class Propose(Message):
    proposal_id: str
    kind: str
    params: dict[str, Any] = {}


@message("governance", "second")
class Second(Message):
    proposal_id: str


@message("governance", "vote")
class Vote(Message):
    proposal_id: str
    choice: Literal["yes", "no", "abstain"]


@message("governance", "enact")
class Enact(Message):
    proposal_id: str
    passed: bool
    facilitator: str
