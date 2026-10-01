"""What every command shares: the co-op it acts for, signing and sending protocol messages, capacity, citations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.domain.ids import ContractId
from commons.protocol import Envelope, Message
from commons.substrate.bus import RateLimited

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.community import Community
    from commons.domain.contract import Contract

MAX_ARTIFACT = 4000
MAX_NOTE = 500


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

    def _cites_ok(self, cites: tuple[str, ...]) -> Outcome | None:
        unknown = [c for c in cites if c not in self.w.library]
        return Outcome(False, f"unknown playbook(s): {', '.join(unknown)}") if unknown else None
