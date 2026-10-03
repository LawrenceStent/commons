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

    [gate]                       # web access and anything else outside (see commons/application/gate.py)
    read = "ask"
    allow_hosts = ["en.wikipedia.org"]

The world re-reads the folder at the start of every cycle; a change takes effect on the next turn and is
recorded in the activity log.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any

from commons.domain.gate import GateError, GatePolicy
from commons.domain.operator import (
    LIMIT_KEYS,
    MAX_CONTEXT,
    MAX_DIRECTIVES,
    RUNTIME_KEYS,
    Limits,
    OperatorError,
    OperatorView,
    _expand_forbid,
    _tighter,
)


class Operator:
    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None
        self.fingerprint = ""
        self.views: dict[str, OperatorView] = {}
        self.all = OperatorView()
        self.errors: list[str] = []
        self.gate = GatePolicy()  # no hosts: no web
        self.desk_tools: frozenset[str] = frozenset()  # the pack's own tools, which limits may name too
        self.reload()

    def know(self, desk_tools) -> None:
        """The pack's desk tools: limits may forbid them by name. Re-reads the folder with them known."""
        self.desk_tools = frozenset(desk_tools)
        self.fingerprint = ""
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
            forbid=bl.forbid | _expand_forbid(lim.get("forbid", []), self.desk_tools),
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
