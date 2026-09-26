"""The activity log: every agent's actions and decisions, and every change they caused.

Three kinds of entry, one timeline:
    action    a call through the actions executor: who, what, with which arguments, what happened
              (scripted and LLM agents alike, because every action goes through the executor)
    decision  what a steward said while deciding, or the `why` it attached to an action
    change    a consequence in the world: a job paid or failed, a contract closed, an audit, a spawn,
              a fork, a playbook published, a kill-switch

In memory the log is a bounded ring (the dashboard reads it). With a path, every entry is also
appended to a JSONL file, so a long run keeps its full history on disk rather than in RAM.
"""

from __future__ import annotations

import inspect
import json
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from substrate.telemetry import Event, Hub


@dataclass(frozen=True)
class Entry:
    seq: int
    cycle: int | None
    community: str | None
    actor: str  # scripted | steward | member | world
    kind: str  # action | decision | change
    name: str  # the action or change, e.g. "bid", "job.paid"
    text: str  # one line a person can read
    ok: bool | None = None
    args: dict[str, Any] = field(default_factory=dict)
    why: str = ""


def _short(v: Any, limit: int = 160) -> Any:
    if isinstance(v, str):
        return v if len(v) <= limit else f"{v[:limit]}… ({len(v)} chars)"
    if isinstance(v, (list, tuple)):
        return [_short(x, limit) for x in v][:12]
    if isinstance(v, dict):
        return {k: _short(x, limit) for k, x in list(v.items())[:12]}
    return v


def _change(ev: Event) -> tuple[str, str | None, str] | None:
    """(name, community, text) for telemetry events that change the world; None for the rest."""
    f = ev.fields
    match ev.kind:
        case "market.job" if f.get("stage") in ("paid", "failed"):
            why = f" ({f['why']})" if f.get("why") else ""
            return f"job.{f['stage']}", f.get("prime"), f"job {f['id']} {f['stage']}{why}"
        case "contract.stage" if f.get("stage") not in ("open", "awarded", "delivered"):
            return (f"contract.{f['stage']}", f.get("prime"),
                    f"contract {f['id']} {f['stage']} (prime {f['prime']}, contractor {f.get('winner') or 'none'})")
        case "contract.stage" if f.get("stage") == "awarded":
            return "contract.awarded", f.get("prime"), f"contract {f['id']} awarded to {f['winner']} at {f['price']}"
        case "grader.grade":
            return ("grade", None, f"{'audit of ' + f['audit'] if f.get('audit') else 'job ' + str(f['job'])} {f['part']}: "
                                   f"{f['score']:.2f}{' — ' + f['reason'] if f.get('reason') else ''}")
        case "knowledge.publish":
            return "playbook.published", f.get("author"), f"playbook {f['id']} on {f['capability']}: {f.get('title', '')}"
        case "population.spawn":
            return "spawn", f["community"], f"{f['agent']} joined {f['community']} as {f['role']} (seconded by {f['seconded_by']})"
        case "population.fork":
            return "fork", f["parent"], f"{f['child']} forked from {f['parent']} with {f['members']} members"
        case "population.merge":
            return "merge", f["target"], f"{f['joiner']} merged into {f['target']}"
        case "population.learn":
            return "learn", f["community"], f"{f['community']} learned {f['capability']}"
        case "population.retire":
            return "retire", f["community"], f"{f['agent']} retired"
        case "meter.kill_switch":
            return "kill_switch", None, f"kill-switch: {f.get('reason')}"
    return None


class ActivityLog:
    def __init__(self, keep: int = 2000, path: str | None = None):
        self.ring: deque[Entry] = deque(maxlen=keep)
        self.path = path
        self._file = open(path, "a") if path else None
        self._seq = 0

    def add(self, cycle, community, actor, kind, name, text, ok=None, args=None, why="") -> Entry:
        self._seq += 1
        e = Entry(self._seq, cycle, community, actor, kind, name, text[:500], ok, _short(args or {}), (why or "")[:300])
        self.ring.append(e)
        if self._file:
            self._file.write(json.dumps(asdict(e)) + "\n")
            self._file.flush()
        return e

    def watch(self, hub: Hub) -> None:
        """Record world changes from telemetry as they happen."""
        def on(ev: Event) -> None:
            c = _change(ev)
            if c:
                self.add(ev.cycle, c[1], "world", "change", c[0], c[2])
        hub.subscribe(on)

    def recent(self, n: int = 100, community: str | None = None, kind: str | None = None) -> list[Entry]:
        out = [e for e in self.ring if (community is None or e.community == community) and (kind is None or e.kind == kind)]
        return out[-n:]

    def close(self) -> None:
        if self._file:
            self._file.close()


def logged(name: str, fn: Callable) -> Callable:
    """Wrap an actions-executor method so every call lands in the world's activity log."""
    sig = inspect.signature(fn)

    def wrapper(self, *a, **kw):
        out = fn(self, *a, **kw)
        try:
            bound = sig.bind(self, *a, **kw)
            args = {k: v for k, v in bound.arguments.items() if k != "self"}
        except TypeError:
            args = {}
        if "artifact" in args:
            args["artifact"] = f"({len(args['artifact'] or '')} chars)"
        why, self.why = getattr(self, "why", ""), ""
        self.w.activity.add(self.w.cycle, self.me.name, getattr(self, "actor", "scripted"), "action", name,
                            out.message, out.ok, args, why)
        return out

    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper
