"""Hooks the LLM runtime calls about itself (not tools an agent is offered): billing model calls, transcripts,
what its operator says, and spending."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from commons.application.commands.base import CommandBase
from commons.application.commands.pipeline import command
from commons.application.observation import Outcome
from commons.domain.money import Micros
from commons.domain.status import JobStatus
from commons.substrate.ledger import InsufficientFunds

if TYPE_CHECKING:
    pass


class RuntimeHooks(CommandBase):
    @command(log=False)
    def record_call(self, role: str, model: str, price_as: str, usage, real: bool, ms: int | None = None,
                    cache_hit: float | None = None) -> int:
        """Charge a model call to this community: notionally always, in USD too when real.
        Raises InsufficientFunds when the purse can't pay, and KillSwitch at a ceiling."""
        cost = self.w.meter.charge_usage(self.me.name, price_as, usage, cycle=self.w.cycle, real=real)
        self.w.thinking_spend[self.me.name] += cost
        self.w.hub.emit("llm.call", self.w.cycle, community=self.me.name, role=role, model=model,
                        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                        cache_read=usage.cache_read_input_tokens, cache_hit=cache_hit, cost=cost, ms=ms, real=real)
        return cost

    @command(log=False)
    def observe(self):
        """A fresh view mid-turn: after a claim or an award, the start-of-turn observation is stale."""
        return self.w.observe(self.me)

    @command(log=False)
    def record_transcript(self, entries: list[dict], started: float | None = None) -> None:
        self.w.transcripts[self.me.name].append({"cycle": self.w.cycle, "entries": entries[-80:]})
        tools = [e for e in entries if e["kind"] == "tool"]
        self.w.hub.emit("llm.turn", self.w.cycle, community=self.me.name, tools=len(tools),
                        ok=sum(e["ok"] for e in tools), names=[e["name"] for e in tools],
                        said=sum(e["kind"] == "say" for e in entries), errors=[e["text"] for e in entries if e["kind"] == "error"],
                        entries=entries[-80:], started=started, ended=time.time())

    @command(log=False)
    def pack(self):
        """What this society is for (its brief, member instructions): the same for every co-op."""
        return self.w.pack

    @command(log=False)
    def operator_view(self):
        """What this co-op's operator has told it: directives, context, limits, runtime settings."""
        return self.w.operator.view(self.me.name)

    @command(log=False)
    def operator_refusal(self, action: str, args: dict) -> str | None:
        held = sum(j.prime == self.me.name and j.status == JobStatus.CLAIMED for j in self.w.jobs.values())
        return self.w.operator.check(self.me.name, action, args, held)

    @command(log=False)
    def record_member_work(self, args: dict, out: Outcome) -> None:
        """A member's commissioned work: part of the action log even though it runs in the runtime."""
        why, self.why = self.why, ""
        self.w.activity.add(self.w.cycle, self.me.name, "member", "action", "commission", out.message, out.ok, args, why)

    @command(log=False)
    def record_decision(self, text: str) -> None:
        """What the steward said while deciding: the decision log's words, next to its actions."""
        if text.strip():
            self.w.activity.add(self.w.cycle, self.me.name, self.actor, "decision", "said", text.strip())

    @command(log=False)
    def spend(self, amount: Micros, memo: str) -> Outcome:
        try:
            self.w.meter.charge(self.me.name, amount, cycle=self.w.cycle, memo=memo)
            return Outcome(True, f"spent {amount}")
        except InsufficientFunds:
            return Outcome(False, f"can't afford {amount}")
