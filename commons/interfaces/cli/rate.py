"""Rate a sample of a society's work: the human anchor of its scorecard (see commons/application/ratings.py).

    uv run commons rate NAME                       # one piece at a time: 0-3, s to skip, q to stop
    uv run commons rate NAME --list                # what is waiting
    uv run commons rate NAME --id RUN/J12 --rating 2 --note "clear, usable"

Ratings: 0 wrong or harmful · 1 not useful · 2 useful · 3 very useful. A running society picks up new ratings at
the start of its next cycle.
"""

import argparse
import sys
import textwrap

from commons.application import founding
from commons.application.ratings import add, unrated
from commons.domain.ratings import SCALE

ap = argparse.ArgumentParser(description="rate a society's sampled work")
ap.add_argument("name")
ap.add_argument("--list", action="store_true")
ap.add_argument("--id")
ap.add_argument("--rating", type=int, choices=sorted(SCALE))
ap.add_argument("--note", default="")
a = ap.parse_args()

try:
    folder = founding.society_folder(a.name)
except founding.FoundingError as e:
    sys.exit(str(e))
waiting = unrated(folder)

if a.id or a.rating is not None:
    if not (a.id and a.rating is not None):
        sys.exit("pass both --id and --rating")
    if a.id not in {s["id"] for s in waiting}:
        print(f"note: {a.id} isn't waiting (already rated, or not a sample); recording it anyway")
    add(folder, a.id, a.rating, a.note)
    print(f"rated {a.id} {a.rating} ({SCALE[a.rating]})")
    sys.exit()

if a.list or not waiting:
    print(f"{len(waiting)} waiting" + (":" if waiting else ""))
    for s in waiting:
        print(f"  {s['id']}  {s['title']}  (by {s['prime']}, grades {', '.join(f'{k} {v:.1f}' for k, v in s['scores'].items())})")
    sys.exit()

print("Rate each piece: " + " · ".join(f"{k} {v}" for k, v in SCALE.items()) + " · s skip · q stop. "
      "Add a note after the number, e.g. `2 clear, but the cost is a guess`.\n")
for s in waiting:
    print("=" * 78)
    print(f"{s['id']}: {s['title']}   (by {s['prime']}, cycle {s['cycle']})")
    for cap, part in s["parts"].items():
        who = "" if part["by"] == s["prime"] else f", by {part['by']}"
        print(f"\n--- {cap} (grade {s['scores'].get(cap, 0):.1f}{who})")
        print(textwrap.indent(part["text"].strip(), "  "))
    while True:
        answer = input("\nrating> ").strip()
        if answer.lower() in ("q", "s"):
            break
        head, _, note = answer.partition(" ")
        if head.isdigit() and int(head) in SCALE:
            add(folder, s["id"], int(head), note.strip())
            break
        print("0, 1, 2 or 3 (optionally followed by a note), s or q")
    if answer.lower() == "q":
        break
