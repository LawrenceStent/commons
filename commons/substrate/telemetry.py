"""The telemetry hub: every component reports here, and the dashboard reads from here.

Components call `hub.emit(kind, cycle=..., **fields)`. The hub keeps the last `ring` events of
each kind and a running count per kind, so memory stays bounded however long a run goes.
Subscribers (the dashboard's event stream) get each event as it happens; a subscriber that
raises is dropped rather than allowed to stall the world.
"""

from __future__ import annotations

import itertools
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str  # "<component>.<what>", e.g. "ledger.transfer", "bus.publish", "llm.call"
    cycle: int | None
    at: float
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def component(self) -> str:
        return self.kind.split(".", 1)[0]


Subscriber = Callable[[Event], None]


class Hub:
    def __init__(self, ring: int = 500, max_kinds: int = 256):
        self.ring = ring
        self.max_kinds = max_kinds
        self.counts: Counter[str] = Counter()
        self._rings: dict[str, deque[Event]] = {}
        self._subs: list[Subscriber] = []
        self._seq = itertools.count(1)

    def emit(self, kind: str, cycle: int | None = None, /, **fields: Any) -> Event:
        ev = Event(next(self._seq), kind, cycle, time.time(), fields)
        self.counts[kind] += 1
        ring = self._rings.get(kind)
        if ring is None:
            if len(self._rings) >= self.max_kinds:
                raise ValueError(f"too many telemetry kinds (> {self.max_kinds}); is {kind!r} carrying an id?")
            ring = self._rings[kind] = deque(maxlen=self.ring)
        ring.append(ev)
        for sub in list(self._subs):
            try:
                sub(ev)
            except Exception:
                self._subs.remove(sub)
        return ev

    def __getstate__(self) -> dict:
        """Saved without its subscribers (they belong to the process that made them; whoever resumes subscribes
        again), and with the next sequence number as a plain number."""
        state = self.__dict__.copy()
        n = next(self._seq)
        self._seq = itertools.count(n)  # put back the number just taken
        state.update(_subs=[], _seq=n)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state, _seq=itertools.count(state["_seq"]))

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subs.append(fn)

        def unsubscribe() -> None:
            if fn in self._subs:
                self._subs.remove(fn)

        return unsubscribe

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def kept(self) -> dict[str, int]:
        """How many events each kind's ring holds now."""
        return {k: len(r) for k, r in self._rings.items()}

    def recent(self, kind: str | None = None, n: int = 50) -> list[Event]:
        """The last `n` events of one kind, or of a whole component with `kind="bus."`."""
        if kind in self._rings:
            return list(self._rings[kind])[-n:]
        rings = [r for k, r in self._rings.items() if kind is None or k.startswith(kind)]
        merged = sorted((e for r in rings for e in itertools.islice(reversed(r), n)), key=lambda e: e.seq)
        return merged[-n:]



class _NullHub(Hub):
    """For components built without a hub: emitting does nothing and keeps nothing."""

    def emit(self, kind: str, cycle: int | None = None, /, **fields: Any) -> None:  # type: ignore[override]
        return None


NULL: Hub = _NullHub(ring=1)
