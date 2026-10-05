"""Every society on this machine, and whether it's paused (K8).

A society is a folder: `societies/NAME` if it was founded (commons/application/founding.py), `runs/ticks/NAME` if it
was started by `commons tick`. A ticked society keeps its state in `STATE/` (`state/` inside its folder) with a
`status.json` written at every save: its pack, cycle, last tick and spend, so listing never has to load a society.
A `paused` file in the folder pauses it: ticks skip it until it's removed (`commons resume NAME`).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

FOUNDED = Path("societies")
TICKED = Path("runs") / "ticks"
STATE = "state"


@dataclass(frozen=True)
class Entry:
    name: str
    folder: Path
    founded: bool
    status: dict  # from state/status.json; empty if it has never been ticked

    @property
    def paused(self) -> bool:
        return (self.folder / "paused").exists()

    @property
    def state(self) -> Path:
        return self.folder / STATE


def folder_of(name: str) -> Path:
    """Where a society lives: its founded folder if there is one, else its ticked one."""
    return FOUNDED / name if (FOUNDED / name / "society.toml").exists() else TICKED / name


def societies() -> list[Entry]:
    found = [(p, True) for p in sorted(FOUNDED.glob("*/society.toml"))]
    ticked = [(p, False) for p in sorted(TICKED.glob(f"*/{STATE}/status.json"))]
    out = {}
    for path, founded in found + ticked:
        folder = path.parent if founded else path.parent.parent
        out.setdefault(folder.name, Entry(folder.name, folder, founded, read_status(folder / STATE)))
    return sorted(out.values(), key=lambda e: e.name)


def read_status(state: Path) -> dict:
    try:
        return json.loads((state / "status.json").read_text())
    except (OSError, ValueError):
        return {}


def write_status(state: Path, world, *, real_spent: int) -> None:
    status = {"pack": world.pack.name, "cycle": world.cycle, "last_tick": round(time.time()),
              "real_spent": real_spent, "halted": world.meter.halted}
    (state / "status.json").write_text(json.dumps(status, indent=1) + "\n")


def pause(name: str) -> Path:
    folder = folder_of(name)
    if not folder.exists():
        raise ValueError(f"no society called {name!r} (commons list shows them)")
    (folder / "paused").write_text(f"paused {time.strftime('%Y-%m-%d %H:%M')}\n")
    return folder


def resume(name: str) -> Path:
    folder = folder_of(name)
    (folder / "paused").unlink(missing_ok=True)
    return folder
