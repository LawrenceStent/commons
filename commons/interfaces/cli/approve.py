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


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons approve", description="decide a society's gate requests")
    ap.add_argument("name", help="the society")
    ap.add_argument("--all", action="store_true", help="decide every waiting request")
    ap.add_argument("--group", type=int, action="append", help="decide a numbered group (repeatable)")
    ap.add_argument("--id", action="append", help="decide one request (repeatable)")
    ap.add_argument("--deny", action="store_true", help="deny instead of approve")
    ap.add_argument("--always", action="store_true", help="with approval: that co-op's future reads from that host too")
    ap.add_argument("--reason", default="", help="told to the co-op with the decision")
    return ap


def grouped(waiting: list[dict]) -> list[tuple[tuple, list[dict]]]:
    """Waiting requests by (co-op, tool, host), numbered in this order."""
    groups: dict[tuple, list[dict]] = {}
    for r in waiting:
        groups.setdefault((r["coop"], r["tool"], r["host"]), []).append(r)
    return sorted(groups.items())


def listing(waiting, ordered) -> None:
    if not waiting:
        sys.exit("nothing waiting")
    for n, ((coop, tool, host), rs) in enumerate(ordered, 1):
        print(f"[{n}] {coop} · {tool} · {host} · {len(rs)} request(s)")
        for r in rs[:8]:
            print(f"      {r['id']}  {r['target'][:100]}")
            for line in str(r.get("detail") or "").splitlines()[:40]:  # what would go public or take effect
                print(f"          {line}")
    print("\nApprove with --all, --group N or --id ID (add --always for a standing approval), or deny with --deny.")


def chosen(a, waiting, ordered) -> list[dict]:
    out = list(waiting) if a.all else []
    for n in a.group or []:
        if not 1 <= n <= len(ordered):
            sys.exit(f"no group {n}; there are {len(ordered)}")
        out += ordered[n - 1][1]
    known = {r["id"]: r for r in waiting}
    for rid in a.id or []:
        if rid not in known:
            sys.exit(f"{rid} isn't waiting (already decided, or not a request)")
        out.append(known[rid])
    return list({r["id"]: r for r in out}.values())


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    try:
        folder = founding.society_folder(a.name)
    except founding.FoundingError as e:
        sys.exit(str(e))
    waiting = pending_in(folder)
    ordered = grouped(waiting)
    if not (a.all or a.group or a.id):
        return listing(waiting, ordered)
    for r in chosen(a, waiting, ordered):
        record(folder, r["id"], not a.deny, a.always and not a.deny, a.reason)
        print(f"{'denied' if a.deny else 'approved'} {r['id']} ({r['tool']} {r['target'][:80]})")


if __name__ == "__main__":
    main()
