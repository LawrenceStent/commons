"""Approve or deny what a society's agents asked the gate for (see commons/application/gate.py), from the command line.

    uv run commons approve NAME                    # what's waiting, grouped by co-op, tool and host
    uv run commons approve NAME --all              # approve everything waiting
    uv run commons approve NAME --group 2          # approve the second group
    uv run commons approve NAME --id RUN/G3 --deny --reason "not relevant"
    uv run commons approve NAME --group 1 --always # approve, and let that co-op read from that host from now on

A running society picks up decisions at the start of its next cycle; approved requests run then. The dashboard
does the same while it's open.
"""

import argparse
import sys

from commons.application import founding
from commons.application.gate import pending_in, record

ap = argparse.ArgumentParser(description="decide a society's gate requests")
ap.add_argument("name")
ap.add_argument("--all", action="store_true", help="decide every waiting request")
ap.add_argument("--group", type=int, action="append", help="decide a numbered group (repeatable)")
ap.add_argument("--id", action="append", help="decide one request (repeatable)")
ap.add_argument("--deny", action="store_true")
ap.add_argument("--always", action="store_true", help="with approval: that co-op's future reads from that host too")
ap.add_argument("--reason", default="")
a = ap.parse_args()

try:
    folder = founding.society_folder(a.name)
except founding.FoundingError as e:
    sys.exit(str(e))
waiting = pending_in(folder)
groups: dict[tuple, list[dict]] = {}
for r in waiting:
    groups.setdefault((r["coop"], r["tool"], r["host"]), []).append(r)
ordered = sorted(groups.items())

if not (a.all or a.group or a.id):
    if not waiting:
        sys.exit("nothing waiting")
    for n, ((coop, tool, host), rs) in enumerate(ordered, 1):
        print(f"[{n}] {coop} · {tool} · {host} · {len(rs)} request(s)")
        for r in rs[:8]:
            print(f"      {r['id']}  {r['target'][:100]}")
    print("\nApprove with --all, --group N or --id ID (add --always for a standing approval), or deny with --deny.")
    sys.exit()

chosen = list(waiting) if a.all else []
for n in a.group or []:
    if not 1 <= n <= len(ordered):
        sys.exit(f"no group {n}; there are {len(ordered)}")
    chosen += ordered[n - 1][1]
known = {r["id"]: r for r in waiting}
for rid in a.id or []:
    if rid not in known:
        sys.exit(f"{rid} isn't waiting (already decided, or not a request)")
    chosen.append(known[rid])
for r in {r["id"]: r for r in chosen}.values():
    record(folder, r["id"], not a.deny, a.always and not a.deny, a.reason)
    print(f"{'denied' if a.deny else 'approved'} {r['id']} ({r['tool']} {r['target'][:80]})")
