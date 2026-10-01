"""R11: every command runs through `main(argv)`, so it can be tested; nothing runs at import. These run in a scratch
folder (societies/ and runs/ are relative to where commands run)."""

import importlib
import shutil

import pytest

from commons.interfaces.cli import main as cli
from tests.paths import ROOT


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "society.example", tmp_path / "society.example")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_importing_a_command_runs_nothing(capsys):
    for name in set(cli.COMMANDS.values()):
        importlib.reload(importlib.import_module(f"commons.interfaces.cli.{name}"))
    assert capsys.readouterr().out == ""


def test_help_and_unknown_commands(capsys):
    cli.main([])
    assert "commons run" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown command 'bogus'"):
        cli.main(["bogus"])


def test_sim(scratch, capsys):
    cli.main(["sim", "20", "--seed", "3", "--pack", "tech_for_good"])
    out = capsys.readouterr().out
    assert "jobs paid" in out and "scorecard" in out and "20 cycles in" in out


def test_found_approve_rate_and_approve(scratch, capsys):
    cli.main(["found", "demo", "--brief", "society.example/brief.md", "--context", "society.example/archive"])
    assert "Read and edit societies/demo/blueprints.toml" in capsys.readouterr().out
    cli.main(["found", "demo", "--approve"])
    assert "approved. Run it" in capsys.readouterr().out
    cli.main(["rate", "demo", "--list"])
    assert "0 waiting" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="nothing waiting"):
        cli.main(["approve", "demo"])
    with pytest.raises(SystemExit, match="no society at"):
        cli.main(["rate", "nope"])


def test_run_a_founded_society_with_fake_models(scratch, capsys, monkeypatch):
    import os

    from commons.interfaces.cli import live

    cli.main(["found", "demo", "--brief", "society.example/brief.md", "--context", "society.example/archive"])
    cli.main(["found", "demo", "--approve"])
    capsys.readouterr()
    monkeypatch.setattr(live, "PID", scratch / "runs" / "live.pid")  # released when the process exits
    cli.main(["run", "--society", "demo", "--backend", "fake", "--cycles", "2"])
    out = capsys.readouterr().out
    assert "society demo: 4 co-ops, 2 archive passages" in out and "cycle 2:" in out and "jobs paid" in out
    assert list((scratch / "societies" / "demo" / "runs").glob("live-fake-*.sqlite"))
    assert (scratch / "runs" / "live.pid").read_text() == str(os.getpid())  # one live run at a time


def test_calibrate_with_the_oracle(scratch, capsys):
    cli.main(["calibrate", "--pack", "tech_for_good"])
    assert "agreement 8/8" in capsys.readouterr().out
    cli.main(["calibrate", "--target", "appraiser"])
    assert "manipulation resisted" in capsys.readouterr().out


def test_spend_needs_confirming(scratch):
    with pytest.raises(SystemExit, match="spends real money"):
        cli.main(["calibrate", "--backend", "anthropic"])
    with pytest.raises(SystemExit, match="Pass --model"):
        cli.main(["run", "--backend", "lmstudio"])


def test_golden_regeneration_needs_a_reason(monkeypatch):
    monkeypatch.chdir(ROOT)
    with pytest.raises(SystemExit, match="say why with --approved"):
        cli.main(["golden", "--update"])


def test_metrics(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    cli.main(["metrics"])
    assert "package cycles                           []" in capsys.readouterr().out


def test_console_parses_its_options():
    from commons.interfaces.cli import console

    a = console.parser().parse_args(["--pack", "tech_for_good", "--port", "8123"])
    assert (a.pack, a.port) == ("tech_for_good", 8123)


def test_two_runs_in_the_same_second_get_their_own_ledgers(tmp_path, monkeypatch):
    from commons.interfaces.cli import live

    monkeypatch.setattr(live.time, "strftime", lambda fmt: "20261001-120000")
    first = live._ledger_path(tmp_path, "fake")
    first.touch()
    second = live._ledger_path(tmp_path, "fake")
    assert second != first and not second.exists()
