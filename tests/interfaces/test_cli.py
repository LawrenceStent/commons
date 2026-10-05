"""R11: every command runs through `main(argv)`, so it can be tested; nothing runs at import. These run in a scratch
folder (societies/ and runs/ are relative to where commands run)."""

import importlib
import json
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
    for name in {v.partition(":")[0] for v in cli.COMMANDS.values()}:
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


def test_a_run_stops_when_every_model_call_in_a_cycle_failed():
    from commons.interfaces.cli import live
    from commons.substrate.telemetry import Hub

    hub = Hub()
    hub.emit("llm.turn", 1, ok=3, errors=[])
    hub.emit("llm.turn", 2, ok=0, errors=["steward call failed: LM Studio returned 400: stuck"])
    hub.emit("llm.turn", 2, ok=1, errors=["steward call failed: once"])
    assert live._model_down(hub, 1) is None and live._model_down(hub, 2) is None
    hub.emit("llm.turn", 3, ok=0, errors=["steward call failed: LM Studio returned 400: stuck"])
    hub.emit("llm.turn", 3, ok=0, errors=["steward call failed: LM Studio returned 400: stuck"])
    assert "LM Studio returned 400: stuck" in live._model_down(hub, 3)
    assert live._model_down(hub, 4) is None  # no LLM turns at all is not a failure


def test_ticks_build_a_society_then_resume_it(tmp_path, monkeypatch, capsys):
    from commons.interfaces.cli import live

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "PID", tmp_path / "runs" / "live.pid")
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake", "--cycles", "2"])
    state = tmp_path / "runs" / "ticks" / "paper" / "state"
    assert (state / "society.save").exists() and (state / "ledger.sqlite").exists()
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake", "--cycles", "23"])
    out = capsys.readouterr().out
    assert "cycles 1-2 played" in out and "cycles 3-25 played" in out and "windows settled" in out
    turns = (state / "turns.jsonl").read_text().splitlines()
    assert {json.loads(t)["cycle"] for t in turns} == set(range(1, 26))  # every cycle's turns, across ticks
    from commons.application.society import World

    w = World.resume(state / "society.save", backend=object())  # no model needed to look
    assert w.cycle == 25 and w.desk.settlements and w.ledger.check() is None


def test_list_pause_and_resume(tmp_path, monkeypatch, capsys):
    from commons.interfaces.cli import live

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "PID", tmp_path / "runs" / "live.pid")
    cli.main(["list"])
    assert "no societies yet" in capsys.readouterr().out
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake", "--cycles", "2"])
    cli.main(["tick", "probe", "--pack", "osint", "--backend", "fake", "--cycles", "1"])
    capsys.readouterr()
    cli.main(["list"])
    out = capsys.readouterr().out
    assert "paper" in out and "trading" in out and "probe" in out and "osint" in out
    cli.main(["pause", "paper"])
    cli.main(["tick", "paper", "--backend", "fake"])  # the pack comes from the society
    assert "paused: skipped" in capsys.readouterr().out
    cli.main(["list"])
    assert "paused" in capsys.readouterr().out
    cli.main(["resume", "paper"])
    cli.main(["tick", "paper", "--backend", "fake"])
    assert "cycles 3-3 played" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="is a trading society"):
        cli.main(["tick", "paper", "--pack", "osint", "--backend", "fake"])


def test_a_cap_across_every_society_stops_ticks_and_runs(tmp_path, monkeypatch, capsys):
    from commons.application import registry
    from commons.interfaces.cli import live

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "PID", tmp_path / "runs" / "live.pid")
    registry.record_spend("elsewhere", 1_500_000)
    registry.record_spend("paper", 600_000)
    assert registry.spent_today() == 2_100_000
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake"])
    assert "skipped: today's real spend" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="total-ceiling"):
        cli.main(["run", "--backend", "fake", "--cycles", "1"])
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake", "--total-ceiling", "5"])
    assert "cycles 1-1 played" in capsys.readouterr().out
    assert registry.spent_today(day="2000-01-01") == 0  # by calendar day


def test_tick_all_takes_turns_and_skips_the_paused(tmp_path, monkeypatch, capsys):
    from commons.application import registry
    from commons.interfaces.cli import live

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, "PID", tmp_path / "runs" / "live.pid")
    cli.main(["tick", "paper", "--pack", "trading", "--backend", "fake"])
    cli.main(["tick", "probe", "--pack", "osint", "--backend", "fake"])
    for _ in range(3):  # three scheduled rounds: each society one cycle a round, one after the other
        cli.main(["tick-all", "--backend", "fake"])
    status = {e.name: e.status for e in registry.societies()}
    assert status["paper"]["cycle"] == 4 and status["probe"]["cycle"] == 4
    assert status["paper"]["pack"] == "trading" and status["probe"]["pack"] == "osint"
    cli.main(["pause", "probe"])
    capsys.readouterr()
    cli.main(["tick-all", "--backend", "fake"])
    assert "1 paused: probe" in capsys.readouterr().out
    assert {e.name: e.status["cycle"] for e in registry.societies()} == {"paper": 5, "probe": 4}
    with pytest.raises(SystemExit, match="no --pack"):
        cli.main(["tick-all", "--pack", "trading"])


def test_approve_shows_what_would_go_public(tmp_path, monkeypatch, capsys):
    from commons.application.gate import Gate

    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "societies" / "shop"
    folder.mkdir(parents=True)
    (folder / "society.toml").write_text('pack = "storefront"\nseed = 0\n')
    gate = Gate(folder=folder, run="r1")
    gate.policy = gate.policy.__class__(publish="ask")
    gate.propose("scribes", "steward", "list_product", "publish", "P1", "Title: 30-Day Plan\nPrice: $4.99", 3)
    cli.main(["approve", "shop"])
    out = capsys.readouterr().out
    assert "list_product" in out and "Title: 30-Day Plan" in out and "Price: $4.99" in out


def test_channels_says_which_keys_are_set_never_their_values(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("BFL_API_KEY", "ETSY_KEYSTRING", "ETSY_SHOP_ID", "ETSY_ACCESS_TOKEN", "ETSY_TAXONOMY_ID",
                 "LEMONSQUEEZY_API_KEY", "LEMONSQUEEZY_STORE_ID"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("BFL_API_KEY=very-secret-key\n")
    cli.main(["channels", "--pack", "storefront"])
    out = capsys.readouterr().out
    assert "ready" in out.splitlines()[0] and "etsy" in out and "missing ETSY_KEYSTRING" in out
    assert "very-secret-key" not in out
