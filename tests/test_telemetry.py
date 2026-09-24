import pytest

from substrate.telemetry import Hub


def test_rings_are_bounded_and_counts_are_not():
    hub = Hub(ring=10)
    for i in range(10_000):
        hub.emit("bus.publish", cycle=i, family="contract")
    assert hub.counts["bus.publish"] == 10_000
    recent = hub.recent("bus.publish", n=100)
    assert len(recent) == 10 and recent[-1].cycle == 9_999


def test_recent_merges_a_component_in_order():
    hub = Hub()
    hub.emit("ledger.transfer", amount=1)
    hub.emit("bus.publish")
    hub.emit("ledger.settle", amount=2)
    assert [e.kind for e in hub.recent("ledger.")] == ["ledger.transfer", "ledger.settle"]
    assert [e.component for e in hub.recent()] == ["ledger", "bus", "ledger"]


def test_subscribers_see_events_and_a_broken_one_is_dropped():
    hub, seen = Hub(), []
    unsubscribe = hub.subscribe(seen.append)
    hub.subscribe(lambda e: 1 / 0)
    hub.emit("world.cycle", cycle=1)
    hub.emit("world.cycle", cycle=2)
    assert [e.cycle for e in seen] == [1, 2] and len(hub._subs) == 1
    unsubscribe()
    hub.emit("world.cycle", cycle=3)
    assert len(seen) == 2


def test_unbounded_kinds_are_refused():
    hub = Hub(max_kinds=3)
    for k in "abc":
        hub.emit(f"x.{k}")
    with pytest.raises(ValueError):
        hub.emit("x.d")
