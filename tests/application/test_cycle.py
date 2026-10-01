"""R6.1: the cycle is a list of phases, in the order its docstring gives; only model, web and turn phases run
outside the world's lock."""

from commons.application import cycle


def test_the_phases_run_in_the_documented_order():
    documented = [line.split()[0] for line in cycle.__doc__.split("\n\n")[2].splitlines() if line.strip()]
    assert [p.name for p in cycle.PHASES] == documented


def test_only_waiting_phases_run_outside_the_lock():
    assert {p.name for p in cycle.PHASES if not p.locked} == {"appraise", "web", "turns", "grade"}
