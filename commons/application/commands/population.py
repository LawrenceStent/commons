"""Changing a co-op: spawn, retire, fork, merge, learn. The rules are commons/application/population.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application import charters, population
from commons.application.commands.base import CommandBase
from commons.application.commands.pipeline import command
from commons.application.observation import Outcome
from commons.domain.ids import PlaybookId, ProposalId

if TYPE_CHECKING:
    pass


class PopulationCommands(CommandBase):
    @command()
    def propose_spawn(self, role: str) -> Outcome:
        if (err := self._use_capacity()) is not None:
            return err
        return population.propose_spawn(self.w, self.me, role)

    @command()
    def second_spawn(self, proposal_id: ProposalId) -> Outcome:
        return population.second_spawn(self.w, self.me, proposal_id)

    @command()
    def retire(self) -> Outcome:
        return population.retire(self.w, self.me)

    @command()
    def fork(self, name: str, members: int, capabilities: tuple[str, ...], charter: str = "") -> Outcome:
        if (err := self._use_capacity()) is not None:
            return err
        return population.fork(self.w, self.me, name, int(members), tuple(capabilities), charter)

    @command()
    def propose_merge(self, target: str) -> Outcome:
        if (err := self._use_capacity()) is not None:
            return err
        return population.propose_merge(self.w, self.me, target)

    @command()
    def accept_merge(self, proposal_id: ProposalId) -> Outcome:
        return population.accept_merge(self.w, self.me, proposal_id)

    @command()
    def propose_charter(self, text: str, reason: str = "") -> Outcome:
        """A request for comment on a new charter for this co-op; it goes to the operator after the comment window."""
        if (err := self._use_capacity()) is not None:
            return err
        return charters.propose(self.w, self.me, text, reason)

    @command()
    def comment(self, proposal_id: ProposalId, text: str) -> Outcome:
        return charters.comment(self.w, self.me, proposal_id, text)

    @command()
    def learn(self, capability: str, playbook_id: PlaybookId | None = None) -> Outcome:
        if (err := self._use_capacity()) is not None:
            return err
        return population.learn(self.w, self.me, capability, playbook_id)
