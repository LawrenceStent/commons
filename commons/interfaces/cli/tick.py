"""Play a saved society a few cycles at a time: resume it, play, save it, stop (K6). For forward tests that run for
weeks on a schedule (scripts/tick.sh), so the machine is only busy for minutes at a time.

    uv run commons tick NAME --pack trading --backend fake                       # a free dry tick
    uv run commons tick NAME --pack trading --backend lmstudio --model <id>      # one cycle, a local model
    uv run commons tick NAME --cycles 3 ...

The first tick builds the society, as `commons run` would (the same options); every later one resumes it, with the
models of this tick. Its state lives in societies/NAME/state/ for a founded society, else runs/ticks/NAME/state/:
the save, the ledger, the activity log and every LLM turn. One live run at a time: ticks take the same lock.
"""

import sys
from pathlib import Path

from commons.application.society import World
from commons.interfaces.cli import live

STATE = "state"


def parser():
    ap = live.parser()
    ap.prog, ap.description = "commons tick", "resume a saved society, play a few cycles, save it"
    ap.add_argument("name", help="the society: societies/NAME if founded, else runs/ticks/NAME")
    ap.set_defaults(cycles=1)
    return ap


def folder(a) -> Path:
    if (Path("societies") / a.name).exists():
        a.society = a.name
        return Path("societies") / a.name / STATE
    return Path("runs") / "ticks" / a.name / STATE


def _open(a, state: Path, society, pack, models) -> World:
    save, ledger = state / "society.save", state / "ledger.sqlite"
    if save.exists():
        grader, appraiser = live.judges(a, pack, models)
        world = World.resume(save, grader=grader, appraiser=appraiser, backend=models["backend"], pack=pack)
        world.web = live.web_for(a, world.operator)
        if world.web:
            world.web.set_hosts(world.gate.policy.allow_hosts)
        return world
    if ledger.exists():
        sys.exit(f"{ledger} exists without a save: an earlier tick died before saving. Move the folder aside to start again.")
    return live._world(a, society, pack, models, live._population(society, pack, models), str(ledger))


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    state = folder(a)
    society, pack = live._source(a)
    models = live._models(a)
    state.mkdir(parents=True, exist_ok=True)
    live._lock()
    world = _open(a, state, society, pack, models)
    live._log_turns(world, str(state / "turns.jsonl"))
    start = world.cycle
    a.cycles = start + a.cycles  # the run loop counts from the society's first cycle
    live._run(world, a, str(state / "ledger.sqlite"))
    if world.meter.halted and live._model_down(world.hub, world.cycle):
        world.meter.halted = False  # a stuck model isn't the society's doing: the next tick tries again
    world.save(state / "society.save")
    world.ledger.check()
    settled = [s for s in getattr(world.desk, "settlements", []) if s["cycle"] > start]
    print(f"{a.name}: cycles {start + 1}-{world.cycle} played and saved in {state}"
          + (f" · {len(settled)} windows settled, {sum(s['paid'] for s in settled)} µcr paid" if settled else ""))


if __name__ == "__main__":
    main()
