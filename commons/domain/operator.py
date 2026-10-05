"""What an operator can say to co-ops: directives, context and limits (world rules). See application/operator.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from commons.domain.money import Micros

MAX_DIRECTIVES = 4_000  # characters per co-op (all.md + its own file)
MAX_CONTEXT = 12_000  # characters of reference material per co-op
LIMIT_KEYS = {"forbid", "max_price", "max_jobs", "thinking_budget"}
RUNTIME_KEYS = {"steward_model", "member_model", "max_rounds", "max_tokens", "member_max_tokens"}
ACTIONS = {"claim", "do_part", "announce", "bid", "award", "deliver", "review", "attest", "dispute", "propose_spawn",
           "second_spawn", "retire", "fork", "propose_merge", "accept_merge", "learn", "publish", "read_playbook",
           "note", "idea", "set_goal", "update_goal", "propose_venture", "commission", "search_archive", "read_archive",
           "web_search", "web_fetch", "propose_charter", "comment"}
# natural names for groups of actions; a forbid list may use either
ALIASES = {"merge": {"propose_merge", "accept_merge"}, "spawn": {"propose_spawn"}, "venture": {"propose_venture"},
           "ventures": {"propose_venture"}, "contracting": {"announce", "award"}, "bidding": {"bid"},
           "web": {"web_search", "web_fetch"}}


def _expand_forbid(names, extra: frozenset[str] = frozenset()) -> frozenset[str]:
    """A forbid list that names something the world doesn't know must fail loudly, never silently allow it. `extra`:
    the names of the pack's desk tools (commons/domain/desk.py), which the world knows too."""
    out = set()
    for n in names:
        if n in ALIASES:
            out |= ALIASES[n]
        elif n in ACTIONS or n in extra:
            out.add(n)
        else:
            raise OperatorError(f"forbid names an unknown action {n!r}; use one of {sorted(ACTIONS | extra | set(ALIASES))}")
    return frozenset(out)


@dataclass(frozen=True)
class Limits:
    forbid: frozenset[str] = frozenset()
    max_price: Micros | None = None
    max_jobs: int | None = None
    thinking_budget: Micros | None = None

    def describe(self) -> list[str]:
        out = []
        if self.forbid:
            out.append(f"You may not use: {', '.join(sorted(self.forbid))}.")
        if self.max_price is not None:
            out.append(f"No bid or announcement above {self.max_price} µcr.")
        if self.max_jobs is not None:
            out.append(f"Hold at most {self.max_jobs} open job(s) at a time.")
        if self.thinking_budget is not None:
            out.append(f"Spend at most {self.thinking_budget} µcr on model calls per turn.")
        return out


@dataclass(frozen=True)
class OperatorView:
    """What one co-op gets from its operator."""
    directives: str = ""
    context: tuple[tuple[str, str], ...] = ()  # (file name, text)
    limits: Limits = field(default_factory=Limits)
    runtime: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.directives or self.context or self.limits.describe())


class OperatorError(ValueError):
    pass


def _tighter(a: int | None, b: int | None) -> int | None:
    """A co-op's own limit can only tighten the one set for everyone."""
    vals = [int(v) for v in (a, b) if v is not None]
    return min(vals) if vals else None

