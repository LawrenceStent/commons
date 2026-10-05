"""Every society on this machine (K8): list them, pause one, resume one.

    uv run commons list               each society: pack, cycle, last tick, real spend, paused or not
    uv run commons pause NAME         ticks skip it until it's resumed
    uv run commons resume NAME
    uv run commons pace NAME MINUTES  at most one tick per MINUTES (0: every round of the schedule)
"""

import argparse
import sys
import time

from commons.application import registry


def show(entries) -> str:
    if not entries:
        return "no societies yet (commons found NAME ..., or commons tick NAME --pack P ...)"
    lines = [f"{'society':16} {'pack':14} {'cycle':>6}  {'last tick':16} {'pace':>6} {'real $':>8}  state"]
    for e in entries:
        s = e.status
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["last_tick"])) if s.get("last_tick") else "-"
        state = "paused" if e.paused else ("halted" if s.get("halted") else ("founded" if e.founded and not s else "ok"))
        lines.append(f"{e.name:16} {s.get('pack', '-'):14} {s.get('cycle', '-')!s:>6}  {last:16} "
                     f"{(str(e.pace) + 'm') if e.pace else '-':>6} "
                     f"{s.get('real_spent', 0) / 1e6:>8.4f}  {state}")
    return "\n".join(lines)


def main_list(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(prog="commons list", description="every society on this machine").parse_args(argv)
    print(show(registry.societies()))


def _toggle(verb: str, argv: list[str] | None) -> None:
    ap = argparse.ArgumentParser(prog=f"commons {verb}", description=f"{verb} a society's ticks")
    ap.add_argument("name")
    a = ap.parse_args(argv)
    try:
        folder = (registry.pause if verb == "pause" else registry.resume)(a.name)
    except ValueError as e:
        sys.exit(str(e))
    print(f"{a.name} {'paused' if verb == 'pause' else 'resumed'} ({folder})")


def main_pace(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="commons pace", description="the minutes between a society's ticks")
    ap.add_argument("name")
    ap.add_argument("minutes", type=int, help="0: every round of the schedule")
    a = ap.parse_args(argv)
    try:
        registry.set_pace(a.name, a.minutes)
    except ValueError as e:
        sys.exit(str(e))
    print(f"{a.name} ticks at most every {a.minutes} minutes" if a.minutes else f"{a.name} ticks every round")


def main_pause(argv: list[str] | None = None) -> None:
    _toggle("pause", argv)


def main_resume(argv: list[str] | None = None) -> None:
    _toggle("resume", argv)
