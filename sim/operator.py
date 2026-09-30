"""The operator: what you, the person running a society, tell its co-ops.

Three kinds of input, handled differently because they need to be:

    directives  plain-language instructions ("focus on work for students"). Stewards read them every
                turn in a trusted block of their system prompt, marked as coming from you. They are guidance:
                a model can still misjudge them.
    context     reference material (notes, research, style guides), included as reference and capped in
                size so it can't inflate every call's cost.
    limits      rules the world enforces, whatever a model decides: actions a co-op may not take, a maximum
                price for its bids and announcements, a lower job cap, a thinking budget per turn. Stewards
                are told their limits; the actions executor refuses anything beyond them. Limits apply to
                scripted co-ops too.

Everything lives in a folder you can edit by hand (or from the dashboard's Operator panel):

    operator/
      all.md             directives for every co-op
      coops/<name>.md    directives for one co-op
      context/...        reference files
      config.toml        per co-op (or [all]): context files, limits, runtime settings

config.toml:

    [all]
    context = ["context/house-style.md"]
    [all.limits]
    forbid = ["merge"]

    [coops.studio]
    context = ["context/student-market.md"]
    [coops.studio.limits]
    max_price = 150000        # µcr, for bids and announcements
    max_jobs = 1
    thinking_budget = 60000   # µcr of model calls per turn
    [coops.studio.runtime]
    steward_model = "claude-sonnet-5"
    max_rounds = 6

    [gate]                       # web access and anything else outside (see sim/gate.py)
    read = "ask"
    allow_hosts = ["en.wikipedia.org"]

The world re-reads the folder at the start of every cycle; a change takes effect on the next turn and is
recorded in the activity log.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sim.gate import GateError, GatePolicy

MAX_DIRECTIVES = 4_000  # characters per co-op (all.md + its own file)
MAX_CONTEXT = 12_000  # characters of reference material per co-op
LIMIT_KEYS = {"forbid", "max_price", "max_jobs", "thinking_budget"}
RUNTIME_KEYS = {"steward_model", "member_model", "max_rounds", "max_tokens", "member_max_tokens"}
ACTIONS = {"claim", "do_part", "announce", "bid", "award", "deliver", "review", "attest", "dispute", "propose_spawn",
           "second_spawn", "retire", "fork", "propose_merge", "accept_merge", "learn", "publish", "read_playbook",
           "note", "idea", "set_goal", "update_goal", "propose_venture", "commission", "search_archive", "read_archive",
           "web_search", "web_fetch"}
# natural names for groups of actions; a forbid list may use either
ALIASES = {"merge": {"propose_merge", "accept_merge"}, "spawn": {"propose_spawn"}, "venture": {"propose_venture"},
           "ventures": {"propose_venture"}, "contracting": {"announce", "award"}, "bidding": {"bid"},
           "web": {"web_search", "web_fetch"}}


def _expand_forbid(names) -> frozenset[str]:
    """A forbid list that names something the world doesn't know must fail loudly, never silently allow it."""
    out = set()
    for n in names:
        if n in ALIASES:
            out |= ALIASES[n]
        elif n in ACTIONS:
            out.add(n)
        else:
            raise OperatorError(f"forbid names an unknown action {n!r}; use one of {sorted(ACTIONS | set(ALIASES))}")
    return frozenset(out)


@dataclass(frozen=True)
class Limits:
    forbid: frozenset[str] = frozenset()
    max_price: int | None = None
    max_jobs: int | None = None
    thinking_budget: int | None = None

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


class Operator:
    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None
        self.fingerprint = ""
        self.views: dict[str, OperatorView] = {}
        self.all = OperatorView()
        self.errors: list[str] = []
        self.gate = GatePolicy()  # no hosts: no web
        self.reload()

    # ── loading ────────────────────────────────────────────────
    def _read(self, rel: str) -> str:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise OperatorError(f"{rel} is outside the operator folder")
        return p.read_text() if p.exists() else ""

    def _files(self) -> list[Path]:
        if not self.root or not self.root.exists():
            return []
        return sorted(p for p in self.root.rglob("*") if p.is_file())

    def _fingerprint(self) -> str:
        h = hashlib.sha256()
        for p in self._files():
            h.update(str(p.relative_to(self.root)).encode())
            h.update(p.read_bytes())
        return h.hexdigest()

    def reload(self) -> bool:
        """Re-read the folder if anything changed. Returns True when it did. A broken config keeps the
        last good one and records the error rather than stopping the society."""
        fp = self._fingerprint()
        if fp == self.fingerprint:
            return False
        self.fingerprint = fp
        if not self.root or not self.root.exists():
            self.views, self.all, self.errors, self.gate = {}, OperatorView(), [], GatePolicy()
            return True
        try:
            raw = self._read("config.toml")
            config = tomllib.loads(raw) if raw else {}
            self.all = self._view(config.get("all", {}), self._read("all.md"))
            names = set(config.get("coops", {}))
            names |= {p.stem for p in (self.root / "coops").glob("*.md")} if (self.root / "coops").exists() else set()
            self.views = {n: self._view(config.get("coops", {}).get(n, {}), self._read(f"coops/{n}.md"), base=self.all)
                          for n in sorted(names)}
            if unknown := set(config) - {"all", "coops", "gate"}:
                raise OperatorError(f"unknown config sections {sorted(unknown)}")
            self.gate = GatePolicy.parse(config.get("gate", {}))
            self.errors = []
        except (OperatorError, GateError, tomllib.TOMLDecodeError, TypeError, ValueError) as e:
            self.errors = [f"operator folder not applied: {e}"]
        return True

    def _view(self, cfg: dict, own: str, base: OperatorView | None = None) -> OperatorView:
        unknown = set(cfg) - {"context", "limits", "runtime"}
        if unknown:
            raise OperatorError(f"unknown config keys {sorted(unknown)}")
        lim = cfg.get("limits", {})
        if set(lim) - LIMIT_KEYS:
            raise OperatorError(f"unknown limits {sorted(set(lim) - LIMIT_KEYS)}; allowed: {sorted(LIMIT_KEYS)}")
        run = cfg.get("runtime", {})
        if set(run) - RUNTIME_KEYS:
            raise OperatorError(f"unknown runtime settings {sorted(set(run) - RUNTIME_KEYS)}; allowed: {sorted(RUNTIME_KEYS)}")
        b = base or OperatorView()
        directives = "\n\n".join(t.strip() for t in (b.directives, own) if t and t.strip())[:MAX_DIRECTIVES]
        context, used = list(b.context), sum(len(t) for _, t in b.context)
        for rel in cfg.get("context", []):
            text = self._read(rel)
            if not text:
                raise OperatorError(f"context file {rel} is missing or empty")
            text = text[: max(0, MAX_CONTEXT - used)]
            if text:
                context.append((rel, text))
                used += len(text)
        bl = b.limits
        limits = Limits(
            forbid=bl.forbid | _expand_forbid(lim.get("forbid", [])),
            max_price=_tighter(bl.max_price, lim.get("max_price")),
            max_jobs=_tighter(bl.max_jobs, lim.get("max_jobs")),
            thinking_budget=_tighter(bl.thinking_budget, lim.get("thinking_budget")),
        )
        return OperatorView(directives, tuple(context), limits, {**b.runtime, **run})

    # ── reading ────────────────────────────────────────────────
    def view(self, coop: str) -> OperatorView:
        return self.views.get(coop, self.all)

    def check(self, coop: str, action: str, args: dict[str, Any], held_jobs: int = 0) -> str | None:
        """A reason the operator's limits refuse this action, or None. The world calls this before acting."""
        lim = self.view(coop).limits
        if action in lim.forbid:
            return f"your operator doesn't allow {action.replace('_', ' ')}"
        price = args.get("price", args.get("max_price"))
        if lim.max_price is not None and action in ("bid", "announce") and price is not None and int(price) > lim.max_price:
            return f"your operator caps bids and announcements at {lim.max_price} µcr"
        if lim.max_jobs is not None and action in ("claim", "propose_venture") and held_jobs >= lim.max_jobs:
            return f"your operator limits you to {lim.max_jobs} open job(s)"
        return None

    def set_directives(self, coop: str | None, text: str) -> None:
        """Write directives from the dashboard. `coop=None` means every co-op (all.md)."""
        if not self.root:
            raise OperatorError("this run has no operator folder (start it with --operator DIR)")
        if coop is not None and not coop.replace("-", "").isalnum():
            raise OperatorError(f"bad co-op name {coop!r}")
        path = self.root / ("all.md" if coop is None else f"coops/{coop}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text[:MAX_DIRECTIVES])


def _tighter(a: int | None, b: int | None) -> int | None:
    """A co-op's own limit can only tighten the one set for everyone."""
    vals = [int(v) for v in (a, b) if v is not None]
    return min(vals) if vals else None
