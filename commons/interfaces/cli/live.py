"""Run a society with LLM communities.

    uv run commons run --backend fake                          # free dry run of the whole pipeline
    uv run commons run --backend lmstudio --model <id> --cycles 10 --serve
    uv run commons run --backend anthropic --yes-spend --real-ceiling 1.00 --cycles 10

The population and the live economy come from the pack (`--pack`, default earn_online).

Every run has limits: --cycles, --max-minutes, and for real models a real-dollar ceiling (the
kill-switch). The ledger is written to runs/. With --serve the dashboard runs at
http://localhost:8000 and the run pauses itself at the cycle limit; Ctrl-C stops it.

LM Studio: check memory first (`lms ps`, `memory_pressure`), load one model of at most 8B with an
8k context, and unload it after (`lms unload --all`).
"""

import argparse
import atexit
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import uvicorn

from commons.adapters.models import BackendChoiceError, FakeBackend, add_backend_args, choose_backend
from commons.adapters.web import WebAccess
from commons.agents.llm.fakes import GOOD_GRADE, competent
from commons.agents.llm.steward import LLMStrategy
from commons.agents.scripted import SCRIPTED
from commons.application import founding
from commons.application.archive import Archive
from commons.application.gate import Gate
from commons.application.graders import HybridGrader, LLMGrader, PanelGrader
from commons.application.operator import Operator
from commons.application.ratings import Ratings
from commons.application.services.recorder import summary
from commons.application.society import Params, World
from commons.application.ventures import LLMAppraiser
from commons.domain.community import Community
from commons.domain.pack import load as load_pack
from commons.interfaces.console.app import create_app
from commons.substrate.meter import KillSwitch

PID = Path("runs/live.pid")
RUN = dict(parallel_turns=True, grading_workers=4)  # stewards think at once; grading 4 calls at a time


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons run", description="run a society with LLM co-ops")
    add_backend_args(ap, "steward model (LM Studio: the loaded model's id)")
    ap.add_argument("--pack", default=None, help="which society to run (a folder under packs/; default earn_online)")
    ap.add_argument("--society", help="run a founded society from societies/NAME (its pack, brief, co-ops, archive, operator)")
    ap.add_argument("--member-model", help="the model members write with (default: the steward's locally, haiku on anthropic)")
    ap.add_argument("--grader-model", help="the model that grades and appraises (default: as --member-model)")
    ap.add_argument("--cycles", type=int, default=10, help="stop after this many cycles")
    ap.add_argument("--max-minutes", type=float, default=30, help="stop after this many minutes of wall time")
    ap.add_argument("--seed", type=int, default=0, help="random seed (a founded society uses its own)")
    ap.add_argument("--real-ceiling", type=float, default=1.00, help="real dollars per day before the kill-switch trips")
    ap.add_argument("--serve", action="store_true", help="watch it on the dashboard")
    ap.add_argument("--operator", help="folder of directives, context and limits for the co-ops (see operator.example/)")
    ap.add_argument("--panel", action="store_true",
                    help="grade every part with the pack's panel of graders (median of its lenses; costs one call per lens)")
    ap.add_argument("--rate-every", type=int, default=3,
                    help="with --society: set every Nth paid job aside for you to rate (commons rate NAME)")
    ap.add_argument("--no-web", action="store_true", help="no web access, whatever the operator's [gate] allows")
    ap.add_argument("--reasoning", action="store_true",
                    help="the local model reasons before answering: give every call more room (thinking counts against max_tokens)")
    return ap


def _source(a):
    """(society or None, pack). A founded society brings its own pack, seed and operator folder."""
    if not a.society:
        return None, load_pack(a.pack)
    try:
        society = founding.load(a.society)
    except founding.FoundingError as e:
        sys.exit(str(e))
    a.seed = society.seed
    if not a.operator and (society.folder / "operator").exists():
        a.operator = str(society.folder / "operator")
    return society, society.pack


def _models(a) -> dict:
    """The backend, the models for stewards, members and the grader, and how much room each call gets."""
    try:
        backend, steward = choose_backend(a.backend, a.model, a.yes_spend, default_model="claude-sonnet-5",
                                          fake=lambda: FakeBackend(respond=lambda *x: GOOD_GRADE, converse=competent),
                                          cost="set a daily limit with --real-ceiling")
    except BackendChoiceError as e:
        sys.exit(str(e))
    # members and the grader default to the steward's model locally, and to a cheaper one on Anthropic
    cheaper = "claude-haiku-4-5" if a.backend == "anthropic" else steward
    # Local models cost nothing real, so they get as many tokens as they need (26 Sep): no per-turn budget,
    # and replies bounded only by the context window (load the model with 32k). Thinking is still charged to
    # the purse notionally. Real-money backends keep the caps. Rounds stay bounded either way: that limit stops
    # a steward looping, not thinking.
    if a.backend == "lmstudio":
        room, grader_tokens = {"max_tokens": 16_000, "member_max_tokens": 8_000, "turn_tokens": 10**9}, 12_000
    else:
        room = {"max_tokens": 6000, "member_max_tokens": 2500} if a.reasoning else {}
        grader_tokens = 6000 if a.reasoning else 400
    return dict(backend=backend, steward=steward, member=a.member_model or cheaper, grader=a.grader_model or cheaper,
                room=room, grader_tokens=grader_tokens)


def _population(society, pack, m: dict) -> list[Community]:
    def llm(name, caps, charter, members=3, doctrine=""):
        c = Community(name, members, caps, LLMStrategy(m["backend"], steward_model=m["steward"], member_model=m["member"],
                                                       **m["room"]), charter=charter)
        c.doctrine = doctrine
        return c

    if society:
        return society.population(llm, SCRIPTED)
    if pack.live_population is None:
        sys.exit(f"the {pack.name} pack has no live population")
    return pack.live_population(llm)


def _lock() -> None:
    """runs/live.pid is both this process's real pid (`uv run` wraps us, and a signal sent to the wrapper doesn't
    reach the world) and a lock: one live run at a time, per the resource guardrails. A second run once overwrote and
    then deleted the first run's pid file; now it refuses to start."""
    if PID.exists():
        try:
            other = int(PID.read_text())
            if other != os.getpid():  # this process may take its own lock again (ticks in one test, say)
                os.kill(other, 0)
                sys.exit(f"another live run is active (pid {other}); stop it first: kill -INT {other}")
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # a stale file from a run that died
    PID.parent.mkdir(parents=True, exist_ok=True)
    PID.write_text(str(os.getpid()))
    lock = PID  # the file this run locked, whatever happens to the name later
    atexit.register(lambda: lock.exists() and lock.read_text() == str(os.getpid()) and lock.unlink())


def judges(a, pack, m: dict) -> tuple:
    """The grader and the appraiser this run's models give: built for a new society, reattached to a resumed one."""
    if a.panel and not pack.grader_panel:
        sys.exit(f"the {pack.name} pack has no grader panel")
    judge = (PanelGrader.of(m["backend"], m["grader"], m["grader_tokens"], pack.grader_system, pack.grader_panel) if a.panel
             else LLMGrader(m["backend"], model=m["grader"], max_tokens=m["grader_tokens"], system=pack.grader_system))
    return HybridGrader(judge), LLMAppraiser(m["backend"], model=m["grader"], max_tokens=m["grader_tokens"],
                                             system=pack.appraiser_system)


def web_for(a, operator: Operator | None) -> WebAccess | None:
    return None if a.no_web or a.backend == "fake" else WebAccess.default(operator.gate.search if operator else "wikipedia")


def _world(a, society, pack, m: dict, population, ledger: str) -> World:
    grader, appraiser = judges(a, pack, m)
    run_name = Path(ledger).stem
    operator = Operator(a.operator) if a.operator else None
    make_desk = pack.desk if a.backend == "fake" else (pack.live_desk or pack.desk)  # a dry run never touches live data
    return World(Params(seed=a.seed, ledger_path=ledger, activity_path=ledger.replace(".sqlite", ".activity.jsonl"),
                        **{**pack.live, **RUN}),
                 population=population, pack=pack, grader=grader, appraiser=appraiser,
                 operator=operator, web=web_for(a, operator),
                 gate=Gate(folder=society.folder if society else None, run=run_name),
                 archive=Archive(society.folder / "archive") if society else None,
                 ratings=Ratings(society.folder, run=run_name, every=a.rate_every) if society else None,
                 desk=make_desk(a.seed) if make_desk else None)


def _announce(world: World, society, population, a) -> None:
    if society:
        seeded = society.seed_playbooks(world)
        print(f"society {society.name}: {len(population)} co-ops, {len(world.archive)} archive passages, {seeded} seeded playbooks")
    if world.web and world.gate.policy.allow_hosts:
        print(f"web: {world.gate.policy.read} reads from {', '.join(world.gate.policy.allow_hosts)}"
              + (f" · decide requests on the dashboard or with: uv run commons approve {society.name}" if society else
                 " · decide requests on the dashboard (--serve)" if world.gate.policy.read == "ask" else ""))
    if world.operator.errors:
        sys.exit(f"the operator folder has a problem: {world.operator.errors[0]}")
    world.meter.real_ceiling = round(a.real_ceiling * 1e6)


def _log_turns(world: World, path: str) -> None:
    """Every LLM turn, in full, on disk (the world keeps only the last two per community in memory)."""
    f = open(path, "a")

    def log_turn(ev):
        if ev.kind == "llm.turn":
            f.write(json.dumps({"cycle": ev.cycle, **ev.fields}) + "\n")
            f.flush()

    world.hub.subscribe(log_turn)


def _model_down(hub, cycle: int) -> str | None:
    """Why the run should stop, if every LLM turn this cycle failed on a model error before doing anything: the
    model backend is down or stuck, and more cycles would only wait on it."""
    turns = [e.fields for e in hub.recent("llm.turn", n=hub.ring) if e.cycle == cycle]
    failed = [t["errors"][0] for t in turns if not t["ok"] and t["errors"] and
              t["errors"][0].startswith("steward call failed")]
    if turns and len(failed) == len(turns):
        return f"every model call failed in cycle {cycle} ({failed[0]})"
    return None


def _run(world: World, a, ledger: str) -> None:
    if a.serve:
        print(f"dashboard: http://localhost:8000 · stops at cycle {a.cycles} · ledger {ledger}")
        uvicorn.run(create_app(world, cycles_per_second=5, stop_at=a.cycles), port=8000, log_level="warning")
        # stop with: kill -INT $(cat runs/live.pid). An in-flight model call finishes first (up to its timeout).
        return
    t0 = time.time()
    try:
        while world.cycle < a.cycles and time.time() - t0 < a.max_minutes * 60:
            world.step()
            calls = [e for e in world.hub.recent("llm.call", n=world.hub.ring) if e.cycle == world.cycle]
            print(f"cycle {world.cycle}: {len(calls)} model calls, {time.time() - t0:.0f}s elapsed", flush=True)
            if why := _model_down(world.hub, world.cycle):
                world.meter.halt(why, cycle=world.cycle)
                print(f"STOPPED: {why}")
                break
    except KillSwitch as e:
        print(f"KILL-SWITCH: {e}")


def _report(world: World, society, ledger: str, turns_path: str) -> None:
    world.ledger.check()
    print()
    print(summary(world))
    calls = world.hub.recent("llm.call", n=world.hub.ring)
    by = Counter((e.fields["community"], e.fields["role"]) for e in calls)
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
    if society and world.ratings and world.ratings.samples:
        print(f"{len(world.ratings.samples)} pieces of work set aside for you to rate: uv run commons rate {society.name}")


def _ledger_path(runs: Path, backend: str) -> Path:
    """A ledger file no earlier run has used: runs started in the same second get -2, -3 and so on."""
    stem = f"live-{backend}-{time.strftime('%Y%m%d-%H%M%S')}"
    path, n = runs / f"{stem}.sqlite", 1
    while path.exists():
        n += 1
        path = runs / f"{stem}-{n}.sqlite"
    return path


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    society, pack = _source(a)
    models = _models(a)
    population = _population(society, pack, models)
    runs = society.folder / "runs" if society else Path("runs")
    runs.mkdir(parents=True, exist_ok=True)
    ledger = str(_ledger_path(runs, a.backend))
    _lock()
    world = _world(a, society, pack, models, population, ledger)
    _announce(world, society, population, a)
    turns_path = ledger.replace(".sqlite", ".turns.jsonl")
    _log_turns(world, turns_path)
    _run(world, a, ledger)
    _report(world, society, ledger, turns_path)


if __name__ == "__main__":
    main()
