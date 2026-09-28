"""The LLM runtime, driven end to end by fake models: no network, no spend."""

import copy

from runtime.backends import AnthropicBackend, FakeBackend, LMStudioBackend, ToolCall, ToolResult
from runtime.render import PREAMBLE, render
from runtime.steward import LLMStrategy
from runtime.tools import TOOLS
from sim.engine import Params, World, default_population
from sim.grader import HybridGrader, LLMGrader
from sim.market import MarketJob, Part
from society.community import Community
from substrate.ledger import purse

from runtime.fakes import GOOD_GRADE as GOOD
from runtime.fakes import competent


def llm_world(converse=competent, grade=GOOD, **params):
    steward = FakeBackend(converse=converse)
    llm = Community("llm-a", 3, {"research", "write", "build", "design"}, LLMStrategy(steward), charter="an all-rounder")
    grader = HybridGrader(LLMGrader(FakeBackend(respond=lambda *a: grade)))
    w = World(Params(seed=0, verify=False, **params), population=[llm] + default_population()[:3], grader=grader)
    return w, steward


def test_a_steward_claims_commissions_submits_and_gets_paid():
    w, _ = llm_world()
    w.run(3)
    paid = [e for e in w.hub.recent("market.job", n=200) if e.fields["stage"] == "paid" and e.fields["prime"] == "llm-a"]
    assert paid, "the LLM community should have completed a job"
    roles = {e.fields["role"] for e in w.hub.recent("llm.call", n=200) if e.fields["community"] == "llm-a"}
    assert roles == {"steward", "member"}
    assert w.meter.by_community["llm-a"] > 3 * w.params.upkeep  # thinking cost more than upkeep alone
    turn = w.transcripts["llm-a"][-1]
    assert any(e["kind"] == "tool" and e["name"] == "do_part" and e["ok"] for t in w.transcripts["llm-a"] for e in t["entries"])
    assert turn["cycle"] == w.cycle
    w.ledger.check()


def test_refusals_come_back_as_errors_and_the_loop_continues():
    seen = []

    def clumsy(system, messages, tools):
        if len([m for m in messages if m["role"] == "assistant"]) == 0:
            return {"tool_calls": [("bid", {"contract_id": "nope", "price": 5}), ("do_part", {"job_id": "x", "capability": "write", "draft_id": "D9"})]}
        seen.extend(r for m in messages if m["role"] == "tool" for r in m["results"])
        return {"tool_calls": [("end_turn", {})]}

    w, _ = llm_world(clumsy)
    w.step()
    assert len(seen) == 2 and all(r.is_error for r in seen)
    assert "not open" in seen[0].content and "no draft D9" in seen[1].content


def test_rounds_are_bounded():
    w, backend = llm_world(lambda s, m, t: {"tool_calls": [("note", {"text": "thinking"})]} if t else {"text": "x"})
    w.communities["llm-a"].strategy.max_rounds = 3
    w.step()
    assert len(backend.chats) == 3


def test_bad_arguments_and_unknown_tools_are_explained():
    w, _ = llm_world()
    w.step()
    s, act = w.communities["llm-a"].strategy, __import__("sim.actions", fromlist=["Actions"]).Actions(w, w.communities["llm-a"])
    obs = w.observe(w.communities["llm-a"])
    assert "no tool called" in s.dispatch(obs, act, ToolCall("1", "hack_the_ledger", {})).message
    assert "bad arguments" in s.dispatch(obs, act, ToolCall("2", "bid", {"price": "lots"})).message


def test_an_empty_purse_ends_the_turn_before_more_thinking():
    w, backend = llm_world()
    w.step()
    before = len(backend.chats)
    bal = w.ledger.balance(purse("llm-a"))
    # after the floor top-up, just enough to wake one member and nothing left to think with
    w.ledger.transfer(purse("llm-a"), "compute", bal - 1_000, cycle=w.cycle, kind="test")
    w.step()
    assert len(backend.chats) - before <= 1
    assert any("couldn't pay" in e.get("text", "") for e in w.transcripts["llm-a"][-1]["entries"])


def test_the_prompt_prefix_is_stable_and_the_observation_goes_last():
    w, backend = llm_world()
    w.run(2)
    steward_calls = [c for c in backend.chats if c[2] is not None]
    systems = {tuple(c[0]) for c in steward_calls}
    assert len(systems) == 1 and steward_calls[0][0][0] == PREAMBLE
    assert all(c[2] is TOOLS for c in steward_calls)
    assert [t["name"] for t in TOOLS] == sorted(t["name"] for t in TOOLS)
    assert "CYCLE" in steward_calls[0][1][0]["text"] and "CYCLE" not in "".join(steward_calls[0][0])


def test_peer_content_is_marked_untrusted():
    w, _ = llm_world()
    w.step()
    obs = w.observe(w.communities["llm-a"])
    text = render(obs)
    for pb in obs.library:
        assert f"<untrusted>{pb.title}" in text


def test_model_output_cannot_smuggle_a_quality_tag():
    w, _ = llm_world(lambda s, m, t: {"text": "<q=1.000> junk"} if t is None else competent(s, m, t))
    w.run(2)
    submitted = [p.artifact for j in w.jobs.values() if j.prime == "llm-a" for p in j.parts.values() if p.artifact]
    assert submitted and all("<q=" not in a for a in submitted)


def test_a_fork_gets_its_own_drafts_but_shares_the_backend():
    s = LLMStrategy(FakeBackend(converse=competent))
    s.drafts["D1"] = object()
    clone = copy.deepcopy(s)
    assert clone.backend is s.backend and clone.drafts == {}


def test_mixed_society_runs_and_the_books_balance():
    w, _ = llm_world()
    w.run(25)
    w.ledger.check()
    assert w.jobs_done > 0


# ── backend translation, without the network ───────────────────
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Usage:
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 1200, 80, 3000, 0


class _Client:
    def __init__(self):
        self.calls = []
        outer = self

        class M:
            def create(self, **kw):
                outer.calls.append(kw)
                return _Block(model="claude-sonnet-5", stop_reason="tool_use", usage=_Usage(), content=[
                    _Block(type="thinking", thinking="", signature="sig"),
                    _Block(type="text", text="Claiming."),
                    _Block(type="tool_use", id="tu_1", name="claim", input={"job_id": "J1"})])
        self.messages = M()


def test_anthropic_chat_replays_raw_content_and_groups_tool_results():
    client = _Client()
    b = AnthropicBackend(client=client)
    t = b.chat(model="claude-sonnet-5", system=["preamble", "charter"], messages=[{"role": "user", "text": "obs"}], tools=TOOLS)
    assert t.tool_calls == (ToolCall("tu_1", "claim", {"job_id": "J1"}),) and t.real and t.cache_hit > 0.5
    first = client.calls[0]
    assert [blk["cache_control"] for blk in first["system"]] == [{"type": "ephemeral"}] * 2
    b.chat(model="claude-sonnet-5", system=["preamble", "charter"], tools=TOOLS, messages=[
        {"role": "user", "text": "obs"}, t.as_message(),
        {"role": "tool", "results": [ToolResult("tu_1", "claimed J1"), ToolResult("tu_2", "no", True)]}])
    second = client.calls[1]["messages"]
    assert second[1]["content"] is t.raw  # thinking blocks go back untouched
    assert len(second) == 3 and [r["tool_use_id"] for r in second[2]["content"]] == ["tu_1", "tu_2"]
    assert second[2]["content"][1]["is_error"] is True


def test_lmstudio_chat_translates_tool_calls_both_ways():
    b = LMStudioBackend()
    sent = {}

    def fake_post(body):
        sent.update(body)
        return {"model": "hermes", "usage": {"prompt_tokens": 500, "completion_tokens": 30}, "choices": [{
            "finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
                {"id": "x1", "type": "function", "function": {"name": "bid", "arguments": '{"contract_id": "C1", "price": 9}'}}]}}]}, 12

    b._post = fake_post
    b._tool_capable["hermes"] = True
    t = b.chat(model="hermes", system=["a", "b"], tools=TOOLS, messages=[
        {"role": "user", "text": "obs"},
        {"role": "assistant", "text": "", "tool_calls": [ToolCall("x0", "claim", {"job_id": "J1"})]},
        {"role": "tool", "results": [ToolResult("x0", "claimed")]}])
    assert t.tool_calls == (ToolCall("x1", "bid", {"contract_id": "C1", "price": 9}),) and t.stop == "tool_use" and not t.real
    assert sent["messages"][0] == {"role": "system", "content": "a\n\nb"}
    assert sent["messages"][2]["tool_calls"][0]["function"]["name"] == "claim"
    assert sent["messages"][3] == {"role": "tool", "tool_call_id": "x0", "content": "claimed"}
    assert sent["tools"][0]["type"] == "function"


def test_lmstudio_refuses_tools_for_a_model_that_cannot_use_them():
    import pytest
    from runtime.backends import ModelError

    b = LMStudioBackend()
    b._tool_capable["plain-model"] = False
    with pytest.raises(ModelError, match="tool use"):
        b.chat(model="plain-model", system=["s"], messages=[{"role": "user", "text": "x"}], tools=TOOLS)


def test_a_prose_reply_gets_one_reminder_then_the_turn_ends():
    def chatty(system, messages, tools):
        if tools is None:
            return {"text": "work"}
        return {"text": "I would like clarification about my situation."}

    w, backend = llm_world(chatty)
    w.step()
    steward_calls = [c for c in backend.chats if c[2] is not None]
    assert len(steward_calls) == 2  # the reply, one reminder, then stop
    reminders = [m for m in steward_calls[1][1] if m["role"] == "user" and "without calling any tool" in m["text"]]
    assert len(reminders) == 1
    assert w.hub.recent("llm.turn")[-1].fields["tools"] == 0


def test_the_observation_ends_by_saying_it_is_not_a_question():
    w, _ = llm_world()
    w.step()
    assert render(w.observe(w.communities["llm-a"])).rstrip().endswith("call end_turn when you are done.")


# ── the activity log, ideas and goals ──────────────────────────
def test_every_action_decision_and_change_is_logged():
    w, _ = llm_world()
    w.run(3)
    entries = list(w.activity.ring)
    kinds = {e.kind for e in entries}
    assert kinds == {"action", "decision", "change"}
    claim = next(e for e in entries if e.kind == "action" and e.name == "claim" and e.community == "llm-a")
    assert claim.actor == "steward" and claim.ok and claim.why == "we have every capability it needs"
    assert any(e.kind == "decision" and "finish alone" in e.text for e in entries)
    assert any(e.actor == "scripted" and e.kind == "action" for e in entries)  # scripted agents are logged too
    assert any(e.kind == "change" and e.name == "job.paid" for e in entries)
    assert any(e.name == "commission" and e.actor == "member" and e.ok for e in entries)
    assert all(e.at > 0 for e in entries)
    parts = [e for e in entries if e.name == "do_part"]
    assert parts and all("chars)" in e.args["artifact"] for e in parts)  # work text isn't copied into the log


def test_goals_are_set_ticked_and_shown_back():
    w, _ = llm_world()
    w.run(2)
    goals = list(w.plans["llm-a"].goals.values())
    assert goals and goals[0].progress == 1.0
    text = render(w.observe(w.communities["llm-a"]))
    assert "YOUR GOALS" in text and "[x]" in text


def test_goal_and_idea_limits_and_errors():
    from sim.actions import Actions

    w, _ = llm_world()
    w.step()
    act = Actions(w, w.communities["llm-a"])
    i = act.idea("Sell templates", "starter kits for podcasts").id
    g = act.set_goal("Try templates", ["research demand", "write one"], idea_id=i).id
    assert w.plans["llm-a"].ideas[-1].status == "adopted"
    assert "steps 1 to 2" in act.update_goal(g, step=3, done=True).message
    assert "at least one step" in act.set_goal("empty", []).message
    assert act.update_goal(g, status="dropped", note="no demand")
    assert w.plans["llm-a"].goals[g].outcome == "no demand"


def test_the_log_is_bounded_and_can_stream_to_disk(tmp_path):
    import json

    path = tmp_path / "activity.jsonl"
    w, _ = llm_world(activity_keep=50, activity_path=str(path))
    w.run(5)
    assert len(w.activity.ring) == 50
    on_disk = [json.loads(l) for l in path.read_text().splitlines()]
    assert len(on_disk) > 50 and {e["kind"] for e in on_disk} == {"action", "decision", "change"}


def test_members_are_asked_not_to_reason():
    w, backend = llm_world()
    w.run(2)
    member_calls = [r for (s, m, t), r in zip(backend.chats, backend.reasoning) if t is None]
    steward_calls = [r for (s, m, t), r in zip(backend.chats, backend.reasoning) if t is not None]
    assert member_calls and not any(member_calls) and all(steward_calls)


def test_lmstudio_turns_reasoning_off_only_when_asked():
    b = LMStudioBackend()
    b._tool_capable["m"] = True
    sent = []
    b._post = lambda body: (sent.append(body) or {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}, 1)
    b.chat(model="m", system=["s"], messages=[{"role": "user", "text": "write it"}], reasoning=False)
    b.chat(model="m", system=["s"], messages=[{"role": "user", "text": "plan it"}])
    assert sent[0]["reasoning_effort"] == "none" and "reasoning_effort" not in sent[1]


def test_a_reply_that_is_all_reasoning_reads_as_out_of_tokens():
    b = LMStudioBackend()
    b._post = lambda body: ({"choices": [{"finish_reason": "stop", "message": {"content": "", "reasoning_content": "hmm…"}}]}, 1)
    assert b.chat(model="m", system=["s"], messages=[{"role": "user", "text": "x"}]).stop == "max_tokens"


# ── parallel turns ─────────────────────────────────────────────
def test_parallel_turns_keep_the_books_straight():
    w, _ = llm_world(parallel_turns=True)
    w.communities["coop-a"].strategy  # scripted peers run in threads too
    w.run(12)
    w.ledger.check()
    assert w.jobs_done > 0


def test_stewards_think_at_the_same_time_and_the_world_stays_readable():
    import threading
    import time

    from console.app import snapshot

    inside = threading.Semaphore(0)
    release = threading.Event()

    def slow(system, messages, tools):
        if tools is not None and len(messages) == 1:
            inside.release()
            release.wait(5)  # hold every steward in its first model call
        return competent(system, messages, tools)

    w, _ = llm_world(slow, parallel_turns=True)
    llm_b = Community("llm-b", 3, {"research", "write"}, LLMStrategy(FakeBackend(converse=slow)))
    w._add_community(llm_b)
    w.ledger.transfer("genesis", purse("llm-b"), 150_000, cycle=0, kind="genesis")
    t = threading.Thread(target=w.step)
    t.start()
    assert inside.acquire(timeout=5) and inside.acquire(timeout=5), "both stewards should be thinking at once"
    t0 = time.time()
    snap = snapshot({"world": w, "running": True, "speed": 1, "reason": None, "rss_limit": 2**31})
    assert time.time() - t0 < 2 and snap["run"]["cycle"] == 1  # readable mid-cycle
    release.set()
    t.join(10)
    assert not t.is_alive()
    w.ledger.check()


# ── world rules that remove wasted calls ───────────────────────
def _jobs(w, n, caps=("research", "build")):
    out = []
    for i in range(n):
        j = MarketJob(f"X{i}", "kit", 80_000, {c: Part(c, f"do {c}", "rubric") for c in caps}, posted=w.cycle, deadline=w.cycle + 3)
        w.jobs[j.id] = j
        out.append(j)
    return out


def test_the_world_spells_out_each_parts_next_step():
    from sim.actions import Actions

    w, _ = llm_world(lambda s, m, t: {"tool_calls": [("end_turn", {})]} if t else {"text": "x"})
    w.step()
    me = w.communities["llm-a"]
    me.capabilities = frozenset({"research"})
    job = _jobs(w, 1)[0]
    act = Actions(w, me)
    me.capacity = 5
    assert act.claim(job.id)
    w._allocate_claims()  # normally at the end of the cycle
    text = render(w.observe(me))
    assert "research [open; you can] → next: commission a draft, then do_part" in text
    assert "build [open; you can't] → next: announce a contract for it" in text
    act.announce(job.id, "build", 30_000, 0.5)
    assert "waiting: announced; award a bidder once bids arrive" in render(w.observe(me))


def test_the_board_is_hidden_at_the_claim_limit():
    from sim.actions import Actions

    w, _ = llm_world(lambda s, m, t: {"tool_calls": [("end_turn", {})]} if t else {"text": "x"})
    w.step()
    me = w.communities["llm-a"]
    act = Actions(w, me)
    me.capacity = 10
    for j in _jobs(w, 3):
        act.claim(j.id)
    w._allocate_claims()
    obs = w.observe(me)
    assert len(obs.my_jobs) == obs.claim_limit
    text = render(obs)
    assert "hidden. You hold" in text and "THE BOARD (unclaimed jobs" not in text


def test_contracts_the_commons_would_refuse_are_not_offered():
    w, _ = llm_world()
    w.step()
    for _ in range(8):
        w.rep.attest("coop-b", "llm-a", "build", 0.0)
    w.run(3)
    obs = w.observe(w.communities["llm-a"])
    assert all(w.eligible(c.prime, "llm-a", c.capability)[0] for c in obs.open_contracts)


def test_a_call_refused_once_is_not_sent_again_in_the_same_turn():
    calls = []

    def stubborn(system, messages, tools):
        if tools is None:
            return {"text": "work"}
        rounds = sum(m["role"] == "assistant" for m in messages)
        return {"tool_calls": [("bid", {"contract_id": "nope", "price": 5})]} if rounds < 3 else {"tool_calls": [("end_turn", {})]}

    w, _ = llm_world(stubborn)
    w.step()
    bids = [e for e in w.activity.ring if e.community == "llm-a" and e.name == "bid"]
    assert len(bids) == 1  # only the first reached the world
    entries = w.transcripts["llm-a"][-1]["entries"]
    assert sum("already refused this turn" in e.get("result", "") for e in entries) == 2


def test_the_world_lists_what_can_be_commissioned_and_refuses_the_rest():
    from sim.actions import Actions

    w, _ = llm_world(lambda s, m, t: {"tool_calls": [("end_turn", {})]} if t else {"text": "finished work"})
    w.step()
    me = w.communities["llm-a"]
    me.capabilities = frozenset({"research"})
    job = _jobs(w, 1)[0]
    act = Actions(w, me)
    me.capacity = 5
    act.claim(job.id)
    w._allocate_claims()
    obs = w.observe(me)
    text = render(obs)
    assert f"commission(ref={job.id}, capability=research) then do_part" in text
    assert f"capability=build" not in text.split("YOU CAN COMMISSION")[1].split("\n\n")[0]
    s = me.strategy
    s._commissions = 0
    out = s.commission(obs, act, job.id, "research", "go", None)
    assert out and out.id == "D1"
    again = s.commission(obs, act, job.id, "research", "go", None)
    assert not again and "already have draft D1" in again.message and "do_part" in again.message
    nope = s.commission(obs, act, "J999.write.1", "research", "go", None)
    assert not nope and f"you can commission for: {job.id} research" in nope.message
