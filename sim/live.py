"""Run a society with LLM communities.

    uv run python -m sim.live --backend fake                          # free dry run of the whole pipeline
    uv run python -m sim.live --backend lmstudio --model <id> --cycles 10 --serve
    uv run python -m sim.live --backend anthropic --yes-spend --real-ceiling 1.00 --cycles 10

The population and the live economy come from the pack (`--pack`, default earn_online).

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
from sim.operator import Operator
from sim.archive import Archive
from sim.pack import load as load_pack
from sim.ventures import LLMAppraiser
from society.community import Community
from substrate.meter import KillSwitch

ap = argparse.ArgumentParser()
ap.add_argument("--backend", choices=("fake", "lmstudio", "anthropic"), default="fake")
ap.add_argument("--pack", default=None, help="which society to run (a folder under packs/; default earn_online)")
ap.add_argument("--society", help="run a founded society from societies/NAME (its pack, brief, co-ops, archive, operator)")
ap.add_argument("--model", help="steward model (LM Studio: the loaded model's id)")
ap.add_argument("--member-model")
ap.add_argument("--grader-model")
ap.add_argument("--cycles", type=int, default=10)
ap.add_argument("--max-minutes", type=float, default=30)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--real-ceiling", type=float, default=1.00, help="real dollars per day before the kill-switch trips")
ap.add_argument("--yes-spend", action="store_true", help="required for the anthropic backend")
ap.add_argument("--serve", action="store_true", help="watch it on the dashboard")
ap.add_argument("--operator", help="folder of directives, context and limits for the co-ops (see operator.example/)")
ap.add_argument("--reasoning", action="store_true",
                help="the local model reasons before answering: give every call more room (thinking counts against max_tokens)")
a = ap.parse_args()

society = None
if a.society:
    from sim import founding

    try:
        society = founding.load(a.society)
    except founding.FoundingError as e:
        sys.exit(str(e))
    pack = society.pack
    a.seed = society.seed
    if not a.operator and (society.folder / "operator").exists():
        a.operator = str(society.folder / "operator")
else:
    pack = load_pack(a.pack)

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


# Local models cost nothing real, so they get as many tokens as they need (26 Sep): no per-turn budget,
# and replies bounded only by the context window (load the model with 32k). Thinking is still charged to
# the purse notionally. Real-money backends keep the caps. Rounds stay bounded either way: that limit stops
# a steward looping, not thinking.
if a.backend == "lmstudio":
    room = {"max_tokens": 16_000, "member_max_tokens": 8_000, "turn_tokens": 10**9}
    grader_tokens = 12_000
else:
    room = {"max_tokens": 6000, "member_max_tokens": 2500} if a.reasoning else {}
    grader_tokens = 6000 if a.reasoning else 400


def llm(name, caps, charter, members=3, doctrine=""):
    c = Community(name, members, caps, LLMStrategy(backend, steward_model=steward, member_model=member, **room), charter=charter)
    c.doctrine = doctrine
    return c


if society:
    population = society.population(llm)
elif pack.live_population is None:
    sys.exit(f"the {pack.name} pack has no live population")
else:
    population = pack.live_population(llm)
runs = society.folder / "runs" if society else Path("runs")
runs.mkdir(parents=True, exist_ok=True)
ledger = str(runs / f"live-{a.backend}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite")
# runs/live.pid is both this process's real pid (`uv run` wraps us, and a signal sent to the wrapper
# doesn't reach the world) and a lock: one live run at a time, per the resource guardrails. A second run
# once overwrote and then deleted the first run's pid file; now it refuses to start.
import atexit
import os

PID = Path("runs/live.pid")
if PID.exists():
    try:
        other = int(PID.read_text())
        os.kill(other, 0)
        sys.exit(f"another live run is active (pid {other}); stop it first: kill -INT {other}")
    except (ValueError, ProcessLookupError, PermissionError):
        pass  # a stale file from a run that died
PID.write_text(str(os.getpid()))
atexit.register(lambda: PID.read_text() == str(os.getpid()) and PID.unlink())
RUN = dict(parallel_turns=True, grading_workers=4)  # stewards think at once; grading 4 calls at a time
world = World(Params(seed=a.seed, ledger_path=ledger,
                     activity_path=ledger.replace(".sqlite", ".activity.jsonl"), **{**pack.live_params, **RUN}),
              population=population, pack=pack,
              grader=HybridGrader(LLMGrader(backend, model=grader, max_tokens=grader_tokens, system=pack.grader_system)),
              appraiser=LLMAppraiser(backend, model=grader, max_tokens=grader_tokens, system=pack.appraiser_system),
              operator=Operator(a.operator) if a.operator else None,
              archive=Archive(society.folder / "archive") if society else None)
if society:
    seeded = society.seed_playbooks(world)
    print(f"society {society.name}: {len(population)} co-ops, {len(world.archive)} archive passages, {seeded} seeded playbooks")
if world.operator.errors:
    sys.exit(f"the operator folder has a problem: {world.operator.errors[0]}")
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
