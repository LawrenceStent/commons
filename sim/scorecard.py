"""Scorecards: what success means for a society, beyond money.

Credits are fuel: they pay for thinking and drive selection. For a society whose purpose isn't profit they say
nothing about whether it is succeeding, so each pack declares a scorecard of mission metrics. It is the headline
of the society's dashboard and summary; credits sit below it, as operations.

Each metric says who measures it: `code` (computed from the world's records, deterministic), `grader` (from
grades) or `you` (from the ratings you give a sample of the work, see sim/ratings.py). A metric may have a
target (something to reach) and a floor (a line it must never cross; crossing it is a breach, logged).

Every society also gets the general metrics below: efficiency, concentration, cooperation and citations.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sim.engine import World


@dataclass(frozen=True)
class Metric:
    key: str
    title: str
    measure: Callable[[World], float | None]  # None = no data yet
    by: str = "code"  # code | grader | you
    better: str = "up"  # up | down
    unit: str = ""  # "%" (a share, 0..1), "cr" (µcr), or "" (a count or ratio)
    target: float | None = None
    floor: float | None = None  # on the wrong side of this is a breach
    what: str = ""


def evaluate(world: World, metrics) -> list[dict]:
    out = []
    for m in metrics:
        v = m.measure(world)
        status = "no data"
        if v is not None:
            wrong = (lambda x, line: x < line) if m.better == "up" else (lambda x, line: x > line)
            if m.floor is not None and wrong(v, m.floor):
                status = "breach"
            elif m.target is not None and wrong(v, m.target):
                status = "below target"
            else:
                status = "ok"
        out.append({"key": m.key, "title": m.title, "value": v, "by": m.by, "better": m.better, "unit": m.unit,
                    "target": m.target, "floor": m.floor, "status": status, "what": m.what})
    return out


def fmt(row: dict) -> str:
    v = row["value"]
    if v is None:
        return "–"
    if row["unit"] == "%":
        return f"{v:.0%}"
    if row["unit"] == "cr":
        return f"{v / 1e6:.3f} cr"
    return f"{v:.2f}" if isinstance(v, float) and v != int(v) else f"{v:g}"


def report(rows: list[dict]) -> str:
    lines = [f"{'metric':<28} {'value':>10}  {'by':<6} status"]
    for r in rows:
        lines.append(f"{r['title'][:28]:<28} {fmt(r):>10}  {r['by']:<6} {r['status']}")
    return "\n".join(lines)


# ── general metrics, every society ─────────────────────────────
def _efficiency(w: World) -> float | None:
    earned = sum(s.earned for h in w.history.values() for s in h)
    spent = sum(w.meter.by_community.values())
    return round(earned / spent, 3) if spent else None


def _concentration(w: World) -> float | None:
    """Share of paid work that went to the busiest co-op (the plan's Failure 2: one co-op takes everything)."""
    primes = Counter(o["prime"] for o in w.outputs)
    return round(max(primes.values()) / sum(primes.values()), 3) if primes else None


def _cooperation(w: World) -> float | None:
    """Share of paid parts done by someone other than the prime, through a contract."""
    by = [(o["prime"], p["by"]) for o in w.outputs for p in o["parts"].values()]
    return round(sum(prime != who for prime, who in by) / len(by), 3) if by else None


def _citations(w: World) -> float | None:
    n = w.citations["valid"] + w.citations["invalid"]
    return round(w.citations["valid"] / n, 3) if n else None


GENERAL = (
    Metric("efficiency", "Value per unit of thought", _efficiency, what="everything earned ÷ everything spent thinking"),
    Metric("concentration", "Work to the top co-op", _concentration, better="down", unit="%",
           what="share of paid jobs won by the busiest co-op"),
    Metric("cooperation", "Parts done by contract", _cooperation, unit="%",
           what="share of paid parts done by another co-op"),
    Metric("citations", "Archive citations valid", _citations, unit="%", floor=1.0,
           what="cited archive passages that exist; a made-up citation fails its part"),
)


# ── helpers packs use ──────────────────────────────────────────
def rated(w: World) -> list:
    return list(w.ratings.ratings.values()) if w.ratings else []


def useful(w: World) -> float | None:
    r = rated(w)
    return float(sum(x.rating >= 2 for x in r)) if r else None


def useful_share(w: World) -> float | None:
    r = rated(w)
    return round(sum(x.rating >= 2 for x in r) / len(r), 3) if r else None


def harmful(w: World) -> float | None:
    r = rated(w)
    return float(sum(x.rating == 0 for x in r)) if r else None


def cost_per_useful(w: World) -> float | None:
    n = useful(w)
    return round(sum(w.thinking_spend.values()) / n) if n else None


def mean_grade(w: World) -> float | None:
    scores = [s for o in w.outputs for s in o["scores"].values()]
    return round(sum(scores) / len(scores), 3) if scores else None


def distinct_subjects(w: World) -> float | None:
    return float(len({o["title"] for o in w.outputs})) if w.outputs else None
