"""A member at work: the steward commissions one part, and a member model writes it, after up to `member_rounds`
rounds of looking things up (archive, web). The result is kept as a draft (D1, D2, …) that the steward submits by id,
so the artifact never travels back through the steward's context. Every call is billed to the co-op."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from commons.agents.llm.prompts import (
    MEMBER_SYSTEM,
    NO_MORE_LOOKUPS,
    member_prompt,
    playbook_reference,
    sources_reference,
)
from commons.agents.llm.render import commissionable
from commons.agents.llm.tools import MEMBER, member_tools
from commons.application.observation import ActionsAPI, Observation, Outcome
from commons.application.ports import ModelError, ToolResult, Turn
from commons.domain.grading import strip_tags
from commons.domain.ids import PlaybookId
from commons.substrate.ledger import InsufficientFunds

if TYPE_CHECKING:
    from commons.agents.llm.steward import LLMStrategy


@dataclass(frozen=True)
class Draft:
    id: str
    capability: str
    text: str
    cites: tuple[str, ...]
    ref: str = ""  # the job or contract it was written for


class MemberWorker:
    def __init__(self, agent: LLMStrategy):
        self.agent = agent

    def commission(self, act: ActionsAPI, ref: str, capability: str, instructions: str,
                   playbook_id: PlaybookId | None, sources=()) -> Outcome:
        obs = act.observe()  # the job may have been claimed earlier this turn
        checked = self._check(obs, ref, capability)
        if isinstance(checked, Outcome):
            return checked
        reference = self._reference(act, playbook_id, sources)
        if isinstance(reference, Outcome):
            return reference
        tools = member_tools(bool(obs.archive and obs.archive[0]), bool(obs.web))
        prompt = member_prompt(*checked, instructions, reference, lookups=bool(tools), web=bool(obs.web),
                               rounds=self.agent.member_rounds)
        t = self._write(act, prompt, tools)
        if isinstance(t, Outcome):
            return t
        return self._keep(t, ref, capability, playbook_id)

    def _check(self, obs: Observation, ref: str, capability: str) -> tuple[str, str] | Outcome:
        """The part's (spec, rubric), or why it can't be commissioned."""
        a = self.agent
        if capability not in obs.capabilities:
            return Outcome(False, f"none of your members can do {capability}; announce a contract instead")
        if obs.funded < 1 or a._commissions >= max(2, 2 * obs.funded):
            return Outcome(False, "every awake member is already busy this turn")
        options = commissionable(obs)
        match = next(((s, r) for ref_, cap, s, r, _ in options if ref_ == ref and cap == capability), None)
        if match is None:
            valid = ", ".join(f"{r} {c}" for r, c, *_ in options) or "nothing right now"
            return Outcome(False, f"you can't commission {ref} {capability}; you can commission for: {valid}")
        waiting = next((d for d in a.drafts.values() if d.ref == ref and d.capability == capability), None)
        if waiting:
            how = "do_part" if any(r == ref and h == "do_part" for r, _, _, _, h in options) else "deliver"
            return Outcome(False, f"you already have draft {waiting.id} for {ref} {capability}; submit it with {how}")
        return match

    def _reference(self, act: ActionsAPI, playbook_id: PlaybookId | None, sources) -> str | Outcome:
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

    def _write(self, act: ActionsAPI, prompt: str, tools: list) -> Turn | Outcome:
        """Look-up rounds, then the deliverable: the member's last turn, or why it failed."""
        a = self.agent
        messages: list[dict[str, Any]] = [{"role": "user", "text": prompt}]
        for round_ in range(a.member_rounds + 1 if tools else 1):
            last = round_ == a.member_rounds or not tools
            if last and tools:
                messages.append({"role": "user", "text": NO_MORE_LOOKUPS})
            try:
                # members write; they don't plan. Reasoning here only burned the allowance and returned nothing.
                t = a.backend.chat(model=getattr(a, "_member_model", a.member_model),
                                   system=[getattr(a, "_member_system", MEMBER_SYSTEM)], reasoning=False,
                                   messages=messages, tools=None if last else tools,
                                   max_tokens=getattr(a, "_member_max_tokens", a.member_max_tokens))
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

    def _look_up(self, act: ActionsAPI, calls) -> list[ToolResult]:
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

    def _keep(self, t: Turn, ref: str, capability: str, playbook_id: PlaybookId | None) -> Outcome:
        a = self.agent
        a._commissions += 1
        text = strip_tags(t.text).strip()
        if not text:
            why = " (it spent its whole allowance reasoning)" if t.stop == "max_tokens" else ""
            return Outcome(False, f"the member returned nothing{why}; the call was still charged")
        a._seq += 1
        d = Draft(f"D{a._seq}", capability, text, (playbook_id,) if playbook_id else (), ref)
        a.drafts[d.id] = d
        while len(a.drafts) > a.keep_drafts:
            a.drafts.pop(next(iter(a.drafts)))
        preview = text if len(text) <= 400 else text[:400] + " …"
        return Outcome(True, f"draft {d.id} for {capability} ({len(text)} chars):\n{preview}", d.id)
