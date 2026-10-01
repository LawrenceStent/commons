"""R7: every change is published once, as a typed event; subscribers say what co-ops are told and what telemetry
records. Every event type must define both (a forgotten one would raise at the first publish)."""

import inspect

from commons.application import events as handlers
from commons.domain import events as ev
from tests.paths import ROOT


def test_every_event_says_what_follows_from_it():
    kinds = [c for _, c in inspect.getmembers(ev, inspect.isclass) if issubclass(c, ev.Event) and c is not ev.Event]
    assert len(kinds) >= 50
    for kind in kinds:
        assert kind in handlers.notices.registry, f"{kind.__name__} has no notices"
        assert kind in handlers.telemetry.registry, f"{kind.__name__} has no telemetry"


def test_services_report_only_through_events():
    pass

    root = ROOT / "commons" / "application"
    files = list((root / "services").glob("*.py")) + [root / "population.py", root / "society.py", root / "cycle.py"]
    for f in files:
        text = f.read_text()
        for direct in (".tell(", "hub.emit(", "activity.add("):
            assert direct not in text, f"{f.name} reports directly with {direct}"
