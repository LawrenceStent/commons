"""The LLM runtime: a community whose turns are taken by a model.

Each turn is one fresh conversation:
    system   [frozen preamble, this community's charter]      both cached
    user     this cycle's observation, rendered as text        volatile, last
    then up to `max_rounds` rounds of tool calls, each executed by the actions executor, until the
    steward calls end_turn, stops calling tools, or the turn's token budget runs out.

Members are model calls too: `commission` asks a member model to write the work for one part and
keeps it as a draft (D1, D2, ...). `do_part` and `deliver` submit drafts by id, so the artifact never
travels back through the steward's context. A draft written from a playbook cites it.

Every call is charged to the community's purse through the executor. If the purse can't pay, the
turn ends there: thinking you can't afford doesn't happen.
"""

from __future__ import annotations

import copy
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

from commons.agents.llm.member import Draft, MemberWorker
from commons.agents.llm.prompts import MEMBER_SYSTEM, NUDGE, steward_system
from commons.agents.llm.render import render
from commons.agents.llm.tools import NAMES, steward_tools
from commons.agents.waking import members_to_wake
from commons.application.observation import ActionsAPI, Observation, Outcome
from commons.application.ports import ModelBackend, ModelError, ToolCall, ToolResult
from commons.domain.ids import PlaybookId
from commons.substrate.ledger import InsufficientFunds

__all__ = ["LLMStrategy", "Draft", "MEMBER_SYSTEM"]

# tools whose arguments only need converting; commission, do_part and deliver go through the runtime
CALLS = {
    "announce": lambda act, a: act.announce(str(a["job_id"]), str(a["capability"]), int(a["max_price"]),
                                            float(a["advance_frac"])),
    "bid": lambda act, a: act.bid(str(a["contract_id"]), int(a["price"])),
    "attest": lambda act, a: act.attest(str(a["contract_id"]), float(a["outcome"])),
    "review": lambda act, a: act.review(str(a["contract_id"]), bool(a["accept"]), str(a.get("reason", ""))),
    "fork": lambda act, a: act.fork(str(a["name"]), int(a["members"]), tuple(a["capabilities"]), str(a.get("charter", ""))),
    "learn": lambda act, a: act.learn(str(a["capability"]), a.get("playbook_id") or None),
    "retire": lambda act, a: act.retire(),
    "propose_venture": lambda act, a: act.propose_venture(str(a["title"]), str(a["pitch"]), list(a["parts"]),
                                                          a.get("idea_id") or None),
    "set_goal": lambda act, a: act.set_goal(str(a["title"]), [str(x) for x in a["steps"]], a.get("idea_id") or None),
    "update_goal": lambda act, a: act.update_goal(str(a["goal_id"]), int(a["step"]) if a.get("step") is not None else None,
                                                  bool(a["done"]) if a.get("done") is not None else None,
                                                  str(a.get("note", "")), a.get("status") or None),
}


class LLMStrategy:
    """An agent (commons.domain.community.Agent) whose turns are taken by a model."""
    name = "llm"
    gossips = True

    def __init__(self, backend: ModelBackend, steward_model: str = "claude-sonnet-5",
                 member_model: str = "claude-haiku-4-5", max_rounds: int = 8, turn_tokens: int = 80_000,
                 max_tokens: int = 4096, member_max_tokens: int = 1200, keep_drafts: int = 20, member_rounds: int = 4):
        self.rng = random.Random(0)  # the world reseeds this per community
        self.backend = backend
        self.steward_model, self.member_model = steward_model, member_model
        self.max_rounds, self.turn_tokens = max_rounds, turn_tokens
        self.max_tokens, self.member_max_tokens, self.keep_drafts = max_tokens, member_max_tokens, keep_drafts
        self.member_rounds = member_rounds  # look-ups a member may make (archive, web) before it must write
        self.members = MemberWorker(backend, member_model, member_max_tokens, member_rounds, keep_drafts)

    @property
    def drafts(self) -> dict[str, Draft]:
        return self.members.drafts

    def __deepcopy__(self, memo):
        """A fork gets its own drafts and counters but shares the backend (and its client)."""
        clone = copy.copy(self)
        clone.members = self.members.fresh()
        return clone

    def wake(self, obs: Observation) -> int:
        """How many members to wake: the default rule (commons/agents/waking.py)."""
        return members_to_wake(obs)

    def turn(self, obs: Observation, act: ActionsAPI) -> None:
        StewardLoop(self, obs, act).run()

    # ── tools ──────────────────────────────────────────────────
    def dispatch(self, obs: Observation, act: ActionsAPI, call: ToolCall) -> Outcome:
        a = dict(call.input)
        act.why = str(a.pop("why", "") or "")[:300]
        if call.name not in NAMES:
            return Outcome(False, f"there is no tool called {call.name}")
        if call.name == "commission" and (why := act.operator_refusal("commission", a)):
            return Outcome(False, why)  # the executor checks the rest; commission runs in the runtime
        try:
            if call.name == "commission":
                out = self.commission(obs, act, str(a["ref"]), str(a["capability"]), str(a.get("instructions", "")),
                                      a.get("playbook_id") or None, a.get("sources") or ())
                act.record_member_work(a, out)
                return out
            if call.name in ("do_part", "deliver"):
                return self._submit(act, call.name, a)
            if call.name in CALLS:
                return CALLS[call.name](act, a)
            return getattr(act, call.name)(**{k: v for k, v in a.items()})
        except (KeyError, TypeError, ValueError) as e:
            return Outcome(False, f"bad arguments for {call.name}: {e}")

    def _submit(self, act: ActionsAPI, tool: str, a: dict) -> Outcome:
        """A draft, by id, as a part of the co-op's own job (do_part) or a contract it won (deliver)."""
        d = self.drafts.get(str(a["draft_id"]))
        if d is None:
            return Outcome(False, f"no draft {a['draft_id']}; commission one first")
        if tool == "do_part":
            out = act.do_part(str(a["job_id"]), str(a["capability"]), d.text, d.cites)
        else:
            out = act.deliver(str(a["contract_id"]), d.text, d.cites)
        if out:
            self.drafts.pop(d.id, None)  # used: the part is done
        return out

    def commission(self, obs: Observation, act: ActionsAPI, ref: str, capability: str, instructions: str,
                   playbook_id: PlaybookId | None, sources=()) -> Outcome:
        return self.members.commission(act, ref, capability, instructions, playbook_id, sources)


@dataclass
class StewardLoop:
    """One turn: a fresh conversation of up to `max_rounds` rounds, each a model call and the tools it asked for,
    until the steward calls end_turn, stops calling tools (after one reminder), runs out of budget or tokens, or the
    purse can't pay for more thinking."""
    agent: LLMStrategy
    obs: Observation
    act: ActionsAPI
    messages: list = field(default_factory=list)
    log: list = field(default_factory=list)
    refused: dict = field(default_factory=dict)  # (tool, args) refused this turn -> why
    cost: int = 0
    spent: int = 0
    nudged: bool = False

    def run(self) -> None:
        started = time.time()
        a, act = self.agent, self.act
        act.actor = "steward"
        op, pack = act.operator_view(), act.pack()
        self.system = steward_system(pack, self.obs, op)
        rt = op.runtime  # per-co-op runtime settings from the operator override the defaults for this turn
        self.model = rt.get("steward_model", a.steward_model)
        self.max_tokens = int(rt.get("max_tokens", a.max_tokens))
        a.members.begin_turn(pack.member_system or MEMBER_SYSTEM, rt.get("member_model", a.member_model),
                             int(rt.get("member_max_tokens", a.member_max_tokens)))
        self.budget = op.limits.thinking_budget
        self.messages = [{"role": "user", "text": render(self.obs)}]
        for _ in range(int(rt.get("max_rounds", a.max_rounds))):
            if not self._round():
                break
        act.record_transcript(self.log, started)

    def _round(self) -> bool:
        """One model call and the tools it asked for. False ends the turn."""
        a, act, log = self.agent, self.act, self.log
        if self.budget is not None and self.cost >= self.budget:
            log.append({"kind": "error", "text": f"the operator's thinking budget ({self.budget} µcr a turn) is spent; turn over"})
            return False
        if why := act.thinking_refusal():
            log.append({"kind": "error", "text": why})
            return False
        try:
            t = a.backend.chat(model=self.model, system=self.system, messages=self.messages,
                               tools=steward_tools(bool(self.obs.web)), max_tokens=self.max_tokens)
        except ModelError as e:
            log.append({"kind": "error", "text": f"steward call failed: {e}"})
            return False
        try:
            self.cost += act.record_call("steward", t.model, t.price_as, t.usage, t.real, t.ms, t.cache_hit)
        except InsufficientFunds:
            log.append({"kind": "error", "text": "the purse couldn't pay for that thinking; turn over"})
            return False
        self.spent += t.usage.input_tokens + t.usage.output_tokens + t.usage.cache_read_input_tokens
        self.messages.append(t.as_message())
        if t.text.strip():
            log.append({"kind": "say", "text": t.text.strip()[:1000]})
            act.record_decision(t.text[:1000])
        if not t.tool_calls:
            if self.nudged or t.stop == "max_tokens":
                return False
            # small models often answer the observation in prose; nothing happens without a tool call
            self.nudged = True
            self.messages.append({"role": "user", "text": NUDGE})
            log.append({"kind": "error", "text": "no tool call; reminded once"})
            return True
        results, done = self._run_tools(t.tool_calls)
        self.messages.append({"role": "tool", "results": results})
        if done:
            return False
        if self.spent >= a.turn_tokens:
            log.append({"kind": "error", "text": f"turn budget of {a.turn_tokens} tokens used; turn over"})
            return False
        if t.stop == "max_tokens":
            log.append({"kind": "error", "text": "the steward ran out of output tokens"})
        return True

    def _run_tools(self, calls) -> tuple[list[ToolResult], bool]:
        results, done = [], False
        for call in calls:
            if call.name == "end_turn":
                done = True
                results.append(ToolResult(call.id, "turn ended"))
                continue
            key = (call.name, json.dumps({k: v for k, v in call.input.items() if k != "why"}, sort_keys=True))
            if key in self.refused:
                # the same call, refused earlier this turn, would be refused again: don't ask the world twice
                out = Outcome(False, f"already refused this turn: {self.refused[key]}")
            else:
                out = self.agent.dispatch(self.obs, self.act, call)
                if not out.ok:
                    self.refused[key] = out.message
            results.append(ToolResult(call.id, out.message, not out.ok))
            self.log.append({"kind": "tool", "name": call.name, "input": _short(call.input), "ok": out.ok,
                             "result": out.message[:300]})
        return results, done


def _short(v: Any, limit: int = 200) -> Any:
    if isinstance(v, dict):
        return {k: _short(x, limit) for k, x in v.items()}
    if isinstance(v, str) and len(v) > limit:
        return v[:limit] + " …"
    return v
