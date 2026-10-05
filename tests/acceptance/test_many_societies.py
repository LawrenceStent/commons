"""K8's done-when (FRAMEWORK.md §9): two societies run on alternate schedules on one machine, within the guardrails.
A trading society every round and an OSINT society every other one, ticked by the scheduler one after the other in
one process, under one lock, with a paused one skipped and the cap across societies respected."""

import pytest

from commons.application import registry
from commons.interfaces.cli import live
from commons.interfaces.cli import main as cli


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "PID", tmp_path / "runs" / "live.pid")
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(registry.time, "time", lambda: clock["now"])
    return clock


def cycles():
    return {e.name: e.status["cycle"] for e in registry.societies()}


def test_two_societies_take_turns_on_their_own_schedules(machine, capsys):
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake"])
    cli.main(["tick", "probe", "--pack", "osint", "--backend", "fake"])
    cli.main(["pace", "paper", "60"])
    cli.main(["pace", "probe", "120"])
    for _ in range(4):  # four hourly rounds of the schedule
        machine["now"] += 3600
        cli.main(["tick-all", "--backend", "fake"])
    assert cycles() == {"paper": 5, "probe": 3}  # hourly; every other hour
    assert "not due yet: probe" in capsys.readouterr().out


def test_the_guardrails_hold_across_societies(machine, capsys, tmp_path):
    import os

    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake"])
    cli.main(["tick", "probe", "--pack", "osint", "--backend", "fake"])
    cli.main(["pause", "probe"])
    machine["now"] += 3600
    cli.main(["tick-all", "--backend", "fake"])
    assert cycles() == {"paper": 2, "probe": 1}  # the paused one waits
    registry.record_spend("elsewhere", 5_000_000)
    cli.main(["tick-all", "--backend", "fake"])
    assert cycles() == {"paper": 2, "probe": 1}  # the day's cap across societies is spent
    assert "skipped: today's real spend" in capsys.readouterr().out
    (tmp_path / "runs" / "live.pid").write_text(str(os.getppid()))  # another live process holds the lock
    with pytest.raises(SystemExit, match="another live run"):
        cli.main(["tick", "paper", "--backend", "fake", "--total-ceiling", "100"])
