"""Run a society with LLM communities.

    uv run python -m sim.live --backend fake                          # free dry run of the whole pipeline
    uv run python -m sim.live --backend lmstudio --model <id> --cycles 10 --serve
    uv run python -m sim.live --backend anthropic --yes-spend --real-ceiling 1.00 --cycles 10

The population: two LLM seed communities that need each other (studio: design+write; lab:
research+build), one scripted cooperator, and the scripted defector.

Every run has limits: --cycles, --max-minutes, and for real models a real-dollar ceiling (the
kill-switch). The ledger is written to runs/. With --serve the dashboard runs at
http://localhost:8000 and the run pauses itself at the cycle limit; Ctrl-C stops it.

LM Studio: check memory first (`lms ps`, `memory_pressure`), load one model of at most 8B with an
8k context, and unload it after (`lms unload --all`).
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

from runtime.backends import AnthropicBackend, FakeBackend, LMStudioBackend
from runtime.fakes import GOOD_GRADE, competent
from runtime.steward import LLMStrategy
from sim.engine import Params, World, summary
from sim.grader import HybridGrader, LLMGrader
from society.community import Community
from society.strategies import Cooperator, Defector
from substrate.meter import KillSwitch

ap = argparse.ArgumentParser()
ap.add_argument("--backend", choices=("fake", "lmstudio", "anthropic"), default="fake")
ap.add_argument("--model", help="steward model (LM Studio: the loaded model's id)")
ap.add_argument("--member-model")
ap.add_argument("--grader-model")
ap.add_argument("--cycles", type=int, default=10)
ap.add_argument("--max-minutes", type=float, default=30)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--real-ceiling", type=float, default=1.00, help="real dollars per day before the kill-switch trips")
ap.add_argument("--yes-spend", action="store_true", help="required for the anthropic backend")
ap.add_argument("--serve", action="store_true", help="watch it on the dashboard")
ap.add_argument("--reasoning", action="store_true",
                help="the local model reasons before answering: give every call more room (thinking counts against max_tokens)")
a = ap.parse_args()

if a.backend == "anthropic":
    if not a.yes_spend:
        sys.exit("The anthropic backend spends real money. Re-run with --yes-spend (and consider --real-ceiling).")
    backend = AnthropicBackend()
    steward, member, grader = a.model or "claude-sonnet-5", a.member_model or "claude-haiku-4-5", a.grader_model or "claude-haiku-4-5"
elif a.backend == "lmstudio":
    if not a.model:
        sys.exit("Pass --model with the id of the model loaded in LM Studio (see `lms ps`).")
    backend = LMStudioBackend()
    steward, member, grader = a.model, a.member_model or a.model, a.grader_model or a.model
else:
    backend = FakeBackend(respond=lambda *x: GOOD_GRADE, converse=competent)
    steward = member = grader = "fake"


# Reasoning models think before answering, and thinking counts against max_tokens: give stewards room,
# but a cap (thinking is charged). Members never reason (see runtime/steward.py), so they need little.
room = {"max_tokens": 6000, "member_max_tokens": 2500} if a.reasoning else {}
grader_tokens = 6000 if a.reasoning else 400


def llm(name, caps, charter):
    return Community(name, 3, caps, LLMStrategy(backend, steward_model=steward, member_model=member, **room), charter=charter)


population = [
    llm("studio", {"design", "write"}, "We make products people want to buy: names, taglines and copy that sell."),
    llm("lab", {"research", "build"}, "We find out what buyers need and build the tools that serve it."),
    Community("coop-b", 3, {"build", "design"}, Cooperator(), charter="product studio (scripted)"),
    Community("defector", 2, {"research", "build", "design", "write"}, Defector(), charter="we do everything (scripted)"),
]
Path("runs").mkdir(exist_ok=True)
ledger = f"runs/live-{a.backend}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
# this process's own pid: `uv run` wraps us, and a signal sent to the wrapper doesn't reach the world
import atexit
import os

Path("runs/live.pid").write_text(str(os.getpid()))
atexit.register(lambda: Path("runs/live.pid").unlink(missing_ok=True))
# The live economy, calibrated on the 1.5 local runs (26 Sep): a steward call costs about 4,500 µcr
# (about 10,000 when the model reasons), a member call a few thousand, and handling one job takes a
# few turns plus contractors. At the scripted defaults (reward 80k) thinking bankrupted every LLM
# community within three cycles. A 400k reward covers a job's thinking and its contractors with a
# margin, so good work pays and waste still hurts. Tokens are now the main cost of thinking, so upkeep
# falls; deadlines lengthen (effectiveness, not speed); fees and scripted work costs scale with rewards.
LIVE = dict(job_reward=400_000, purse_seed=400_000, treasury_seed=10_000_000, treasury_reserve=10_000_000,
            upkeep=2_000, basic_budget=1_500, floor_cap=4_000, work_cost=40_000, publish_cost=60_000,
            spawn_fee=1_500_000, learn_cost=2_500_000, audit_cost=20_000,
            board_ttl=5, job_ttl=12, bid_window=4, deliver_ttl=5, review_ttl=3, dispute_window=4,
            parallel_turns=True)  # stewards think at the same time; actions still apply one at a time
world = World(Params(seed=a.seed, ledger_path=ledger,
                     activity_path=ledger.replace(".sqlite", ".activity.jsonl"), **LIVE), population=population,
              grader=HybridGrader(LLMGrader(backend, model=grader, max_tokens=grader_tokens)))
world.meter.real_ceiling = round(a.real_ceiling * 1e6)

# every LLM turn, in full, on disk (the world keeps only the last two per community in memory)
import json

turns_path = ledger.replace(".sqlite", ".turns.jsonl")
turns_file = open(turns_path, "a")


def log_turn(ev):
    if ev.kind == "llm.turn":
        turns_file.write(json.dumps({"cycle": ev.cycle, **ev.fields}) + "\n")
        turns_file.flush()


world.hub.subscribe(log_turn)

if a.serve:
    import uvicorn

    from console.app import create_app

    print(f"dashboard: http://localhost:8000 · stops at cycle {a.cycles} · ledger {ledger}")
    uvicorn.run(create_app(world, cycles_per_second=5, stop_at=a.cycles), port=8000, log_level="warning")
    # stop with: kill -INT $(cat runs/live.pid). An in-flight model call finishes first (up to its timeout).
else:
    t0 = time.time()
    try:
        while world.cycle < a.cycles and time.time() - t0 < a.max_minutes * 60:
            world.step()
            calls = [e for e in world.hub.recent("llm.call", n=world.hub.ring) if e.cycle == world.cycle]
            print(f"cycle {world.cycle}: {len(calls)} model calls, {time.time() - t0:.0f}s elapsed", flush=True)
    except KillSwitch as e:
        print(f"KILL-SWITCH: {e}")

world.ledger.check()
print()
print(summary(world))
calls = world.hub.recent("llm.call", n=world.hub.ring)
by = Counter()
for e in calls:
    f = e.fields
    by[(f["community"], f["role"])] += 1
tok_in = sum(e.fields["input_tokens"] + e.fields.get("cache_read", 0) for e in calls)
tok_out = sum(e.fields["output_tokens"] for e in calls)
cached = sum(e.fields.get("cache_read", 0) for e in calls)
print(f"\nmodel calls: {dict(by)}")
print(f"tokens in {tok_in:,} (cached {cached / tok_in:.0%}) · out {tok_out:,}" if tok_in else "no model calls")
print(f"notional cost {sum(e.fields['cost'] for e in calls) / 1e6:.4f} cr · real ${world.ledger.real()['api_spend'] / 1e6:.4f}")
turns = world.hub.recent("llm.turn", n=world.hub.ring)
if turns:
    acted = sum(e.fields["tools"] > 0 for e in turns)
    ok = sum(e.fields["ok"] for e in turns)
    total = sum(e.fields["tools"] for e in turns)
    print(f"turns {len(turns)}: {acted} used tools · tool calls {total} ({ok} succeeded) · "
          f"most used {Counter(n for e in turns for n in e.fields['names']).most_common(6)}")
print(f"ledger: {ledger} · turns: {turns_path} · activity: {ledger.replace('.sqlite', '.activity.jsonl')}")
