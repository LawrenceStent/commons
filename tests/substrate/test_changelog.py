"""The changelog: a society's every action, across runs, in daily logs gzipped when the day is over (12 Oct)."""

import gzip
import json

from commons.application.society import Params, World
from commons.interfaces.cli import changelog as cli
from commons.substrate import changelog


def test_two_runs_of_a_society_land_in_one_log_read_back_in_order(tmp_path):
    for run in ("run-a", "run-b"):
        w = World(Params(seed=0, ledger_path=str(tmp_path / f"{run}.sqlite"), changelog_dir=str(tmp_path / "logs")))
        w.run(3)
        w.activity.close()
    rows = list(changelog.read(tmp_path / "logs"))
    assert {r["run"] for r in rows} == {"run-a", "run-b"} and rows[0]["run"] == "run-a"
    assert all({"cycle", "community", "actor", "name", "text"} <= set(r) for r in rows)


def test_earlier_days_are_gzipped_and_still_read(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    (folder / "2026-01-01.jsonl").write_text(json.dumps({"run": "old", "text": "first"}) + "\n")
    log = changelog.Changelog(folder, run="new")  # opening a log compresses earlier days
    log.write({"text": "second", "at": 0})
    log.close()
    assert not (folder / "2026-01-01.jsonl").exists() and (folder / "2026-01-01.jsonl.gz").exists()
    assert gzip.open(folder / "2026-01-01.jsonl.gz", "rt").read().count("first") == 1
    assert [r["text"] for r in changelog.read(folder)] == ["first", "second"]


def test_commons_log_filters_by_coop_and_cycle(tmp_path, monkeypatch, capsys):
    w = World(Params(seed=0, ledger_path=str(tmp_path / "r.sqlite"), changelog_dir=str(tmp_path / "logs")))
    w.run(4)
    w.activity.close()
    monkeypatch.setattr(cli.registry, "folder_of", lambda name: tmp_path)
    coop = next(iter(w.communities))
    cli.main(["x", "--coop", coop, "--cycle", "2", "--last", "0"])
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(f" c2 {coop}/" in line for line in lines)
