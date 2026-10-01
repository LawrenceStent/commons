"""The recorder: what each co-op did this cycle (won, delivered, earned), a snapshot of every co-op at the end of each
cycle, the scorecard, and the `world.cycle` telemetry the dashboard draws from."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.scorecard import GENERAL
from commons.domain.scorecard import evaluate as evaluate_scorecard
from commons.domain.scorecard import report as scorecard_report
from commons.domain.status import (
    LIVE_CONTRACT,
    JobStatus,
)
from commons.substrate.ledger import purse

if TYPE_CHECKING:
    from commons.application.society import World


class Recorder:
    def __init__(self, world: World):
        self.w = world
        self._stats = {n: Counter() for n in world.communities}  # this cycle's tallies per co-op

    def begin_cycle(self) -> None:
        """Fresh tallies for a new cycle."""
        self._stats = {n: Counter() for n in self.w.communities}

    def track(self, name: str) -> None:
        """A co-op born mid-run (a fork) starts tallying."""
        self._stats[name] = Counter()

    def stat(self, name: str, key: str, n: int = 1) -> None:
        self._stats[name][key] += n

    def efficiency(self, name: str) -> dict[str, float]:
        """Value per unit of thought: what a co-op has earned against what it has spent to think (upkeep, work
        and model calls). Above 1.0 it earns more than its thinking costs."""
        earned = sum(s.earned for s in self.w.history.get(name, []))
        spent = self.w.meter.by_community.get(name, 0)
        return {"earned": earned, "spent": spent, "thinking": self.w.thinking_spend[name],
                "ratio": round(earned / spent, 3) if spent else 0.0}

    def record(self) -> None:
        for name, c in self.w.communities.items():
            s = self._stats[name]
            self.w.history[name].append(Snapshot(
                cycle=self.w.cycle, purse=self.w.ledger.balance(purse(name)), standing=self.w.standing(name),
                allowance=self.w.bus.allowance(name), active=c.active, thinking=c.thinking,
                won=s["won"], delivered_ok=s["ok"], earned=s["earned"],
            ))
        self.w.scorecard = evaluate_scorecard(self.w, tuple(self.w.pack.scorecard) + GENERAL)
        for row in self.w.scorecard:
            if row["status"] == "breach":
                self.w.events.publish(ev.ScorecardBreached(row["key"], row["value"], row["floor"]))
        pipeline = Counter(c.status for c in self.w.contracts.values() if c.status in LIVE_CONTRACT)
        self.w.events.publish(ev.CycleRecorded(dict(
            treasury=self.w.ledger.balance("treasury"),
            jobs_done=self.w.jobs_done, jobs_failed=self.w.jobs_failed, jobs_expired=self.w.jobs_expired,
            board=sum(j.status == JobStatus.OPEN for j in self.w.jobs.values()),
            in_progress=sum(j.status == JobStatus.CLAIMED for j in self.w.jobs.values()),
            pipeline=dict(pipeline),
            grants=self.w.payments.pool_balance() if self.w.payment.pool else None,
            scorecard={r["key"]: r["value"] for r in self.w.scorecard},
            bus_sent=dict(self.w.bus.sent),
            communities={
                n: {"purse": h[-1].purse, "standing": round(h[-1].standing, 4), "allowance": h[-1].allowance,
                    "active": h[-1].active, "thinking": h[-1].thinking, "won": h[-1].won,
                    "ok": h[-1].delivered_ok, "earned": h[-1].earned}
                for n, h in self.w.history.items()
            },
        )))


@dataclass
class Snapshot:
    cycle: int
    purse: int
    standing: float
    allowance: int
    active: bool
    thinking: int
    won: int
    delivered_ok: int
    earned: int


def summary(world: World, window: int = 50) -> str:
    rows = [f"{'community':<10} {'strategy':<11} {'purse cr':>9} {'standing':>8} {'allow':>5} {'active%':>7} {'won':>5} {'ok':>5}"]
    for name, hist in world.history.items():
        c = world.communities[name]
        tail = hist[-window:]
        rows.append(
            f"{name:<10} {c.strategy.name:<11} {hist[-1].purse / 1e6:>9.3f} {hist[-1].standing:>8.3f} "
            f"{hist[-1].allowance:>5} {100 * sum(s.active for s in tail) / len(tail):>6.0f}% "
            f"{sum(s.won for s in hist):>5} {sum(s.delivered_ok for s in hist):>5}"
        )
    rows.append(f"jobs paid {world.jobs_done}, failed {world.jobs_failed}, expired on board {world.jobs_expired}, "
                f"treasury {world.ledger.balance('treasury') / 1e6:.3f} cr, playbooks {len(world.library)}, "
                f"royalties {sum(world.royalties_paid.values()) / 1e6:.3f} cr"
                + (f", grants left {world.payments.pool_balance() / 1e6:.3f} cr" if world.payment.pool else ""))
    if world.scorecard:
        rows += ["", "scorecard", scorecard_report(world.scorecard)]
    return "\n".join(rows)
