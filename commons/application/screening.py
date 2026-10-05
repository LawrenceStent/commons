"""The pack's screen, applied during a run (commons/domain/pack.py `screen`): a web request before the gate sees it,
work at hand-in. A refusal is a screened attempt: published as an event (the co-op is told, telemetry records it),
and if the pack says so the society halts until you reset it. Founding applies the same screen to briefs and
questions (commons/application/founding.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.pack import screened

if TYPE_CHECKING:
    from commons.application.society import World


def screen(w: World, coop: str, kind: str, text: str) -> str | None:
    """Why the attempt is refused (and recorded), or None. Call it under the world's lock."""
    why = screened(w.pack, kind, text)
    if why is None:
        return None
    halt = w.pack.halt_on_screen
    w.events.publish(ev.Screened(coop, kind, text[:200], why, halt))
    if halt:
        w.meter.halt(f"screened attempt by {coop}: {why}", w.cycle)
    return f"refused by this society's screen: {why}" + (" (the society is halted)" if halt else "")
