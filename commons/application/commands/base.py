"""What every command shares: the co-op it acts for, signing and sending protocol messages, capacity, citations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.domain.grading import is_tagged
from commons.domain.ids import ContractId
from commons.protocol import Envelope, Message
from commons.substrate.bus import RateLimited

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.community import Community
    from commons.domain.contract import Contract
    from commons.domain.market import Part

MAX_ARTIFACT = 4000
MAX_NOTE = 500
FORMAT_REFUSED = "format"  # the Outcome id of a hand-in the format rule refused: the draft needs revising, not resending


class CommandBase:
    actor = "scripted"  # the LLM runtime sets "steward"
    why = ""  # a rationale the runtime attaches to the next action, for the decision log

    def __init__(self, world: World, me: Community):
        self.w = world
        self.me = me

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

    def _contract(self, contract_id: ContractId) -> Contract | None:
        return self.w.contracts.get(contract_id)

    def _format_ok(self, part: Part, artifact: str) -> Outcome | None:
        """The part's format, by rule (commons/domain/format.py). Scripted stand-ins (quality-tagged) are judged by
        their tag, as the grader judges them; model-written text never carries a tag (the runtime strips them)."""
        if is_tagged(artifact) or not (problems := part.format.problems(artifact[:MAX_ARTIFACT])):
            return None
        return Outcome(False, f"refused by the format rule for {part.capability}: {'; '.join(problems)}. "
                              f"Revise it ({part.format.describe()}) and hand it in again", FORMAT_REFUSED)

    def _cites_ok(self, cites: tuple[str, ...]) -> Outcome | None:
        unknown = [c for c in cites if c not in self.w.library]
        return Outcome(False, f"unknown playbook(s): {', '.join(unknown)}") if unknown else None
