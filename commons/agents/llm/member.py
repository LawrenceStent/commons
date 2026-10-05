"""A member at work: the steward commissions one part, and a member model writes it, after up to `member_rounds`
rounds of looking things up (archive, web). The result is kept as a draft (D1, D2, …) that the steward submits by id,
so the artifact never travels back through the steward's context. Every call is billed to the co-op."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from commons.agents.llm.prompts import (
    MEMBER_SYSTEM,
    NO_MORE_LOOKUPS,
    member_prompt,
    playbook_reference,
    sources_reference,
)
from commons.agents.llm.render import commissionable
from commons.agents.llm.tools import MEMBER, member_tools
from commons.application.commands.base import size_problems
from commons.application.observation import Observation, Outcome, RuntimeAPI
from commons.application.ports import ModelBackend, ModelError, ToolResult, Turn
from commons.domain.format import Format, words
from commons.domain.grading import strip_tags
from commons.domain.ids import PlaybookId
from commons.substrate.ledger import InsufficientFunds


def _problems(fmt: Format, text: str) -> list[str]:
    """Why a draft would be refused at hand-in: its part's format, or the size cap every piece of work has."""
    return fmt.problems(text) + size_problems(text)


@dataclass(frozen=True)
class Draft:
    id: str
    capability: str
    text: str
    cites: tuple[str, ...]
    ref: str = ""  # the job or contract it was written for


class MemberWorker:
    """A co-op's members: the drafts they've written, and how they're set up this turn."""

    def __init__(self, backend: ModelBackend, model: str, max_tokens: int, rounds: int, keep: int):
        self.backend, self.model, self.max_tokens, self.rounds, self.keep = backend, model, max_tokens, rounds, keep
        self.system = MEMBER_SYSTEM
        self.drafts: dict[str, Draft] = {}
        self.seq = 0  # drafts written, ever: D1, D2, …
        self.commissions = 0  # this turn

    def __getstate__(self) -> dict:  # the model is the run's, not the society's: see LLMStrategy.attach
        return {**self.__dict__, "backend": None}

    def begin_turn(self, system: str, model: str, max_tokens: int) -> None:
        """A new turn: the pack's member instructions and the operator's runtime settings, and a fresh count."""
        self.system, self.model, self.max_tokens, self.commissions = system, model, max_tokens, 0

    def fresh(self) -> MemberWorker:
        """For a fork: the same setup, no drafts."""
        return MemberWorker(self.backend, self.model, self.max_tokens, self.rounds, self.keep)

    def commission(self, act: RuntimeAPI, ref: str, capability: str, instructions: str,
                   playbook_id: PlaybookId | None, sources=()) -> Outcome:
        obs = act.observe()  # the job may have been claimed earlier this turn
        checked = self._check(obs, ref, capability)
        if isinstance(checked, Outcome):
            return checked
        reference = self._reference(act, playbook_id, sources)
        if isinstance(reference, Outcome):
            return reference
        tools = member_tools(bool(obs.archive and obs.archive[0]), bool(obs.web))
        spec, rubric, fmt = checked
        prompt = member_prompt(spec, rubric, instructions, reference, lookups=bool(tools), web=bool(obs.web),
                               rounds=self.rounds, form=fmt.describe())
        t = self._write(act, prompt, tools)
        if isinstance(t, Outcome):
            return t
        if problems := _problems(fmt, strip_tags(t.text).strip()):
            t = self._revise(act, prompt, t, problems, fmt)
            if isinstance(t, Outcome):
                return t
        return self._keep(t, ref, capability, playbook_id, fmt)

    def _check(self, obs: Observation, ref: str, capability: str) -> tuple[str, str, Format] | Outcome:
        """The part's (spec, rubric, format), or why it can't be commissioned."""
        if capability not in obs.capabilities:
            return Outcome(False, f"none of your members can do {capability}; announce a contract instead")
        if obs.funded < 1 or self.commissions >= max(2, 2 * obs.funded):
            return Outcome(False, "every awake member is already busy this turn")
        options = commissionable(obs)
        match = next(((s, r, f) for ref_, cap, s, r, _, f in options if ref_ == ref and cap == capability), None)
        if match is None:
            valid = ", ".join(f"{r} {c}" for r, c, *_ in options) or "nothing right now"
            return Outcome(False, f"you can't commission {ref} {capability}; you can commission for: {valid}")
        waiting = next((d for d in self.drafts.values() if d.ref == ref and d.capability == capability), None)
        if waiting and _problems(match[2], waiting.text):
            self.drafts.pop(waiting.id)  # it would be refused at hand-in: write a new one
        elif waiting:
            how = "do_part" if any(r == ref and h == "do_part" for r, _, _, _, h, _ in options) else "deliver"
            return Outcome(False, f"you already have draft {waiting.id} for {ref} {capability}; submit it with {how}")
        return match

    def _reference(self, act: RuntimeAPI, playbook_id: PlaybookId | None, sources) -> str | Outcome:
        """A playbook and archive passages for the member to work from, or why they couldn't be read."""
        reference = ""
        if playbook_id:
            pb = act.read_playbook(playbook_id)
            if not pb:
                return pb
            reference = playbook_reference(pb.message)
        material = []
        for pid in list(sources)[:3]:
            got = act.read_archive(str(pid))
            if not got:
                return got
            material.append((got.id, got.message.split("\n", 1)[-1]))
        return reference + (sources_reference(material) if material else "")

    def _write(self, act: RuntimeAPI, prompt: str, tools: list) -> Turn | Outcome:
        """Look-up rounds, then the deliverable: the member's last turn, or why it failed."""
        messages: list[dict[str, Any]] = [{"role": "user", "text": prompt}]
        for round_ in range(self.rounds + 1 if tools else 1):
            last = round_ == self.rounds or not tools
            if last and tools:
                messages.append({"role": "user", "text": NO_MORE_LOOKUPS})
            try:
                # members write; they don't plan. Reasoning here only burned the allowance and returned nothing.
                t = self.backend.chat(model=self.model, system=[self.system], reasoning=False, messages=messages,
                                      tools=None if last else tools, max_tokens=self.max_tokens)
            except ModelError as e:
                return Outcome(False, f"the member couldn't do it: {e}")
            try:
                act.record_call("member", t.model, t.price_as, t.usage, t.real, t.ms, t.cache_hit)
            except InsufficientFunds:
                return Outcome(False, "the purse couldn't pay for the member's work")
            if not t.tool_calls:
                break
            messages += [t.as_message(), {"role": "tool", "results": self._look_up(act, t.tool_calls)}]
        return t

    def _revise(self, act: RuntimeAPI, prompt: str, t: Turn, problems: list[str], fmt: Format) -> Turn | Outcome:
        """One more call, without tools, when the draft breaks the part's format: it would be refused at hand-in."""
        messages = [{"role": "user", "text": prompt}, {"role": "assistant", "text": t.text},
                    {"role": "user", "text": f"This breaks the format rule ({'; '.join(problems)}), so it would be "
                                             f"refused. Rewrite it to fit{': ' + fmt.describe() if fmt.describe() else ''}. Keep its citations. "
                                             "Output the deliverable only."}]
        try:
            revised = self.backend.chat(model=self.model, system=[self.system], reasoning=False, messages=messages,
                                        tools=None, max_tokens=self.max_tokens)
        except ModelError as e:
            return Outcome(False, f"the member couldn't revise it: {e}")
        try:
            act.record_call("member", revised.model, revised.price_as, revised.usage, revised.real, revised.ms,
                            revised.cache_hit)
        except InsufficientFunds:
            return Outcome(False, "the purse couldn't pay for the member's revision")
        return revised

    def _look_up(self, act: RuntimeAPI, calls) -> list[ToolResult]:
        """At most three look-ups a round, through the actions API, logged as the member's."""
        results = []
        for call in calls[:3]:
            if call.name not in MEMBER:
                out = Outcome(False, f"members may only use {', '.join(MEMBER)}")
            else:
                args = {k: v for k, v in call.input.items() if k != "why"}
                before, act.actor = act.actor, "member"
                try:
                    out = getattr(act, call.name)(**args)
                except TypeError as e:
                    out = Outcome(False, f"bad arguments for {call.name}: {e}")
                finally:
                    act.actor = before
            results.append(ToolResult(call.id, out.message, not out.ok))
        return results + [ToolResult(c.id, "skipped: at most 3 look-ups a round", True) for c in calls[3:]]

    def _keep(self, t: Turn, ref: str, capability: str, playbook_id: PlaybookId | None, fmt: Format) -> Outcome:
        self.commissions += 1
        text = strip_tags(t.text).strip()
        if not text:
            why = " (it spent its whole allowance reasoning)" if t.stop == "max_tokens" else ""
            return Outcome(False, f"the member returned nothing{why}; the call was still charged")
        self.seq += 1
        d = Draft(f"D{self.seq}", capability, text, (playbook_id,) if playbook_id else (), ref)
        self.drafts[d.id] = d
        while len(self.drafts) > self.keep:
            self.drafts.pop(next(iter(self.drafts)))
        preview = text if len(text) <= 400 else text[:400] + " …"
        warn = (f"\nIt still breaks the format rule ({'; '.join(problems)}) and would be refused at hand-in; "
                "commission it again with instructions to fix that") if (problems := _problems(fmt, text)) else ""
        size = f"{len(text)} chars, {words(text)} words" if fmt.describe() else f"{len(text)} chars"
        return Outcome(True, f"draft {d.id} for {capability} ({size}):\n{preview}{warn}", d.id)
