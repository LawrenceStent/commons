"""K6/T1: a society saves its state and resumes from it, so a long forward test can run a cycle at a time on a
schedule. The proof: every golden run, split in half around a save and a resume, is the same stream for stream."""

import pytest

from commons.application.society import Params, World
from tests.golden.harness import RUNS, capture, load


@pytest.mark.parametrize("name", sorted(RUNS))
def test_a_run_split_by_a_save_and_resume_is_the_same_run(name):
    _, _, cycles, _ = RUNS[name]
    split = capture(name, split=cycles // 2)
    expected = load(name)
    for stream in expected:
        assert split[stream] == expected[stream], f"{name}: {stream} differs after resuming"


def test_a_society_with_its_ledger_in_memory_cannot_be_saved(tmp_path):
    w = World(Params(seed=0))
    with pytest.raises(ValueError, match="on-disk ledger"):
        w.save(tmp_path / "society.save")


def test_resuming_refuses_a_ledger_that_changed_since_the_save(tmp_path):
    w = World(Params(seed=0, ledger_path=str(tmp_path / "ledger.sqlite"))).run(3)
    w.save(tmp_path / "society.save")
    w.ledger.transfer("treasury", "compute", 1, cycle=3, kind="test")  # after the save
    with pytest.raises(ValueError, match="ledger"):
        World.resume(tmp_path / "society.save")
