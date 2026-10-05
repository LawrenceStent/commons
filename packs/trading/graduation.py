"""Stage 1's graduation criteria, written down on 5 Oct 2026 before any result was looked at, and checked by code so
that judging them later is mechanical (FRAMEWORK.md §7.2; docs/K6-PLAN.md T8.3).

A desk graduates to stage 2 (shadow: orders priced against real fills, still on paper) only if, over at least
`MIN_WINDOWS` settled windows:
    - its mean excess return after costs is above zero
    - its score (excess less half the drawdown) is positive in at least `MIN_POSITIVE` of its windows
    - its worst drawdown in any window is under `MAX_DRAWDOWN`
    - it never met the kill criterion, and paused for daily loss at most `MAX_PAUSES` times
The society must also have played at least `MIN_TICKS` of its scheduled ticks, with no limit ever failing to apply
(scripts/tick.sh's log says how many were skipped; the broker's tests say the limits apply). Changing these after
seeing results means starting the window again.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_WINDOWS = 60
MIN_POSITIVE = 0.55
MAX_DRAWDOWN = 0.10
MAX_PAUSES = 3
MIN_TICKS = 0.90


@dataclass(frozen=True)
class Verdict:
    coop: str
    graduates: bool
    reasons: tuple[str, ...]  # what it fails; empty when it graduates


def judge(desk, coop: str) -> Verdict:
    windows = [s for s in desk.settlements if s["coop"] == coop]
    account = desk.accounts.get(coop)
    fails = []
    if len(windows) < MIN_WINDOWS:
        fails.append(f"{len(windows)} windows settled, {MIN_WINDOWS} needed")
    if windows:
        mean_excess = sum(s["excess"] for s in windows) / len(windows)
        positive = sum(s["score"] > 0 for s in windows) / len(windows)
        worst = max(s["drawdown"] for s in windows)
        if mean_excess <= 0:
            fails.append(f"mean excess return {mean_excess:+.2%}, not above zero")
        if positive < MIN_POSITIVE:
            fails.append(f"score positive in {positive:.0%} of windows, {MIN_POSITIVE:.0%} needed")
        if worst >= MAX_DRAWDOWN:
            fails.append(f"worst drawdown {worst:.1%}, must stay under {MAX_DRAWDOWN:.0%}")
    if account is not None and account.stopped:
        fails.append("met the kill criterion")
    if account is not None and account.pauses > MAX_PAUSES:
        fails.append(f"paused for daily loss {account.pauses} times, at most {MAX_PAUSES}")
    return Verdict(coop, not fails, tuple(fails))


def ticks_played(log_lines: list[str]) -> float | None:
    """Of the ticks the schedule started (scripts/tick.sh's log), the share that played rather than skipped."""
    played = sum(" tick: " in line for line in log_lines)
    skipped = sum(" skip: " in line for line in log_lines)
    return played / (played + skipped) if played + skipped else None
