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

from commons.application import registry
from commons.application.society import World
from commons.interfaces.cli import live

STATE = registry.STATE


def parser():
    ap = live.parser()
    ap.prog, ap.description = "commons tick", "resume a saved society, play a few cycles, save it"
    ap.add_argument("name", help="the society: societies/NAME if founded, else runs/ticks/NAME")
    ap.set_defaults(cycles=1)
    return ap


def folder(a) -> Path:
    """The society's state folder; a resumed society keeps the pack it was built with."""
    root = registry.folder_of(a.name)
    if root.parent == registry.FOUNDED:
        a.society = a.name
    recorded = registry.read_status(root / STATE).get("pack")
    if recorded and a.pack not in (None, recorded):
        sys.exit(f"{a.name} is a {recorded} society; leave out --pack, or pass --pack {recorded}")
    a.pack = a.pack or recorded
    return root / STATE


def _open(a, state: Path, society, pack, models) -> World:
    save, ledger = state / "society.save", state / "ledger.sqlite"
    if save.exists():  # the society's own pack, from its save; then judges and the web for it
        world = World.resume(save, backend=models["backend"], pack=pack if society else None)
        world.attach(*live.judges(a, world.pack, models), live.web_for(a, world.operator))
        return world
    if ledger.exists():
        sys.exit(f"{ledger} exists without a save: an earlier tick died before saving. Move the folder aside to start again.")
    return live._world(a, society, pack, models, live._population(society, pack, models), str(ledger))


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    state = folder(a)
    if (state.parent / "paused").exists():
        print(f"{a.name} is paused: skipped (commons resume {a.name})")
        return
    society, pack = live._source(a)
    models = live._models(a)
    state.mkdir(parents=True, exist_ok=True)
    if live.room(a) <= 0:
        print(f"{a.name}: skipped: today's real spend across every society has reached ${a.total_ceiling:.2f}")
        return
    live._lock()
    world = _open(a, state, society, pack, models)
    live._log_turns(world, str(state / "turns.jsonl"))
    start, todo = world.cycle, a.cycles
    for _ in range(todo):  # a cycle at a time, so the cap across societies is rechecked between them
        if live.room(a) <= 0 or world.meter.halted:
            break
        live.within_room(world, a)
        before = world.ledger.real()["spend"]
        a.cycles = world.cycle + 1  # the run loop counts from the society's first cycle
        live._run(world, a, str(state / "ledger.sqlite"))
        registry.record_spend(a.name, world.ledger.real()["spend"] - before)
    if world.meter.halted and live._model_down(world.hub, world.cycle):
        world.meter.halted = False  # a stuck model isn't the society's doing: the next tick tries again
    world.save(state / "society.save")
    world.ledger.check()
    registry.write_status(state, world, real_spent=world.ledger.real()["spend"])
    settled = [s for s in getattr(world.desk, "settlements", []) if s["cycle"] > start]
    print(f"{a.name}: cycles {start + 1}-{world.cycle} played and saved in {state}"
          + (f" · {len(settled)} windows settled, {sum(s['paid'] for s in settled)} µcr paid" if settled else ""))


def main_all(argv: list[str] | None = None) -> None:
    """Every unpaused society, one after another in this process (one lock, one model load in scripts/tick.sh):
    `commons tick-all [tick options]`. Each keeps its own pack; paused ones are skipped."""
    argv = list(argv or [])
    if any(x == "--pack" or x.startswith("--pack=") for x in argv):
        sys.exit("tick-all takes no --pack: each society keeps its own")
    entries = registry.societies()
    paused = [e.name for e in entries if e.paused]
    waiting = [e.name for e in entries if not e.paused and not e.due()]
    due = [e.name for e in entries if not e.paused and e.due()]
    print(f"tick-all: {len(due)} societies" + (f" ({len(paused)} paused: {', '.join(paused)})" if paused else "")
          + (f" ({len(waiting)} not due yet: {', '.join(waiting)})" if waiting else ""))
    for name in due:
        main([name, *argv])


if __name__ == "__main__":
    main()
