"""Every society on this machine, and whether it's paused (K8).

A society is a folder: `societies/NAME` if it was founded (commons/application/founding.py), `runs/ticks/NAME` if it
was started by `commons tick`. A ticked society keeps its state in `STATE/` (`state/` inside its folder) with a
`status.json` written at every save: its pack, cycle, last tick and spend, so listing never has to load a society.
A `paused` file in the folder pauses it: ticks skip it until it's removed (`commons resume NAME`). A `pace` file sets
the minutes between its ticks (`commons pace NAME MINUTES`), so societies can keep different schedules.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

FOUNDED = Path("societies")
TICKED = Path("runs") / "ticks"
STATE = "state"
SPEND = Path("runs") / "spend.json"  # real USD micro-dollars per calendar day, per society: the cap across them all


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

    @property
    def pace(self) -> int:
        """Minutes between its ticks (a `pace` file; none means every round of the schedule)."""
        try:
            return int((self.folder / "pace").read_text().strip())
        except (OSError, ValueError):
            return 0

    def due(self, now: float | None = None) -> bool:
        last = self.status.get("last_tick")
        return not last or (now or time.time()) - last >= self.pace * 60 - 30  # a little slack for the schedule


def folder_of(name: str) -> Path:
    """Where a society lives: its founded folder if there is one, else its ticked one."""
    return FOUNDED / name if (FOUNDED / name / "society.toml").exists() else TICKED / name


def societies() -> list[Entry]:
    found = [(p, True) for p in sorted(FOUNDED.glob("*/society.toml"))]
    ticked = [(p, False) for p in sorted(TICKED.glob(f"*/{STATE}/society.save"))]
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


def spent_today(day: str | None = None) -> int:
    """Real spend today (µ$), every society together."""
    return sum(_spend().get(day or time.strftime("%Y-%m-%d"), {}).values())


def record_spend(name: str, micros: int, day: str | None = None) -> None:
    if micros <= 0:
        return
    book = _spend()
    today = book.setdefault(day or time.strftime("%Y-%m-%d"), {})
    today[name] = today.get(name, 0) + micros
    SPEND.parent.mkdir(parents=True, exist_ok=True)
    SPEND.write_text(json.dumps(book, indent=1, sort_keys=True) + "\n")


def _spend() -> dict:
    try:
        return json.loads(SPEND.read_text())
    except (OSError, ValueError):
        return {}


def set_pace(name: str, minutes: int) -> Path:
    folder = folder_of(name)
    if not folder.exists():
        raise ValueError(f"no society called {name!r} (commons list shows them)")
    (folder / "pace").write_text(f"{max(0, minutes)}\n")
    return folder


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
