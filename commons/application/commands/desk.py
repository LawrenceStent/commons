"""The pack's desk (commons/domain/desk.py), as commands: each desk tool runs like a kernel command, under the
world's lock, checked against your operator's limits by its own name, and logged by its own name."""

from __future__ import annotations

from typing import Any

from commons.application.commands.base import CommandBase
from commons.application.observation import Outcome
from commons.substrate.activity import log_action


class DeskCommands(CommandBase):
    def desk_call(self, tool: str, args: dict[str, Any]) -> Outcome:
        desk = self.w.desk
        if desk is None or tool not in {t["name"] for t in desk.tools}:
            return Outcome(False, f"there is no tool called {tool}")
        with self.w.lock:
            if why := self.operator_refusal(tool, args):
                out = Outcome(False, why)
            else:
                out = Outcome(*desk.call(self.w, self.me.name, tool, dict(args)))
            log_action(self, tool, dict(args), out)
        return out
