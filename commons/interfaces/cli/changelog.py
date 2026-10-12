"""`commons log NAME`: read a society's changelog (commons/substrate/changelog.py), every run, filtered.

    uv run commons log uk-climate                        the last 50 entries
    uv run commons log uk-climate --coop report-cite     one co-op
    uv run commons log uk-climate --cycle 5 --run live-lmstudio-20261011-142557
    uv run commons log uk-climate --name do_part --grep J3 --last 200
    uv run commons log uk-climate --runs                 the runs in the log, with their size and dates
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

from commons.application import registry
from commons.substrate import changelog


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="commons log", description="a society's changelog: every action, every run")
    ap.add_argument("name", help="the society (commons list shows them)")
    ap.add_argument("--run", help="only this run (its ledger's name)")
    ap.add_argument("--coop", help="only this co-op")
    ap.add_argument("--cycle", type=int, help="only this cycle")
    ap.add_argument("--name", dest="action", help="only this action or change (do_part, contract.awarded, ...)")
    ap.add_argument("--grep", help="only entries whose text contains this")
    ap.add_argument("--failed", action="store_true", help="only actions that were refused or failed")
    ap.add_argument("--last", type=int, default=50, help="how many entries to show (default 50; 0 for all)")
    ap.add_argument("--runs", action="store_true", help="list the runs in the log instead")
    a = ap.parse_args(argv)
    folder = registry.folder_of(a.name) / "logs"
    if not folder.exists():
        sys.exit(f"{a.name} has no changelog yet ({folder}): it starts with the next live run")
    if a.runs:
        seen: dict[str, list] = {}
        for e in changelog.read(folder):
            r = seen.setdefault(e.get("run", "?"), [0, e.get("at", 0), 0])
            r[0] += 1
            r[2] = e.get("at", 0)
        for run, (n, first, last) in seen.items():
            print(f"{run:40} {n:6} entries  {time.strftime('%d %b %H:%M', time.localtime(first))} - "
                  f"{time.strftime('%H:%M', time.localtime(last))}")
        return
    rows = [e for e in changelog.read(folder)
            if (a.run is None or e.get("run") == a.run) and (a.coop is None or e.get("community") == a.coop)
            and (a.cycle is None or e.get("cycle") == a.cycle) and (a.action is None or e.get("name") == a.action)
            and (a.grep is None or a.grep.lower() in str(e.get("text", "")).lower())
            and (not a.failed or e.get("ok") is False)]
    shown = rows[-a.last:] if a.last else rows
    for e in shown:
        when = time.strftime("%d %b %H:%M:%S", time.localtime(e.get("at", 0)))
        ok = {True: "ok", False: "NO", None: ""}[e.get("ok")]
        print(f"{when} c{e.get('cycle')} {e.get('community') or '-'}/{e.get('actor')} {e.get('name')} {ok} "
              f"{' '.join(str(e.get('text', '')).split())[:160]}")
    print(f"({len(shown)} of {len(rows)} matching entries; {dict(Counter(e.get('run') for e in rows).most_common(3))})",
          file=sys.stderr)
