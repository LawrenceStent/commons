import json

from fastapi.testclient import TestClient

from commons.application.world import Params, World
from commons.interfaces.console.app import create_app, snapshot
from commons.substrate.telemetry import Hub


def test_dashboard_renders_and_controls():
    app = create_app(World(Params(seed=0)), autostart=False)
    with TestClient(app) as client:
        assert "EventSource" in client.get("/").text
        assert client.get("/api/snapshot").json()["run"]["cycle"] == 0
        assert client.post("/control/step").json()["cycle"] == 1
        for _ in range(5):
            client.post("/control/step")
        snap = client.get("/api/snapshot").json()
        names = {c["name"] for c in snap["communities"]}
        assert {"defector", "coop-a"} <= names
        for panel in ("reputation", "market", "contracts", "ledger", "bus", "knowledge", "llm", "grader", "gate", "host"):
            assert panel in snap
        assert snap["bus"]["tail"] and snap["ledger"]["recent"]
        assert client.post("/control/resume").json()["running"]
        assert not client.post("/control/pause").json()["running"]
        assert client.post("/control/speed?value=10").json()["speed"] == 10
        assert client.post("/control/nonsense").status_code == 400


def test_kill_switch_blocks_resume_until_reset():
    app = create_app(World(Params(seed=0)), autostart=False)
    with TestClient(app) as client:
        run = client.post("/control/kill").json()
        assert run["halted"] and not run["running"] and "kill-switch" in run["pause_reason"]
        assert client.post("/control/resume").status_code == 409
        assert not client.post("/control/reset-kill").json()["halted"]
        assert client.post("/control/resume").json()["running"]


def test_memory_guard_pauses_the_run():
    app = create_app(World(Params(seed=0)), autostart=True, rss_limit=1, host_every=0.0)
    with TestClient(app) as client:
        for _ in range(50):
            run = client.get("/api/snapshot").json()["run"]
            if not run["running"]:
                break
            import time; time.sleep(0.05)
        assert not run["running"] and "memory guard" in run["pause_reason"]


def test_community_drilldown():
    w = World(Params(seed=0)).run(5)
    with TestClient(create_app(w, autostart=False)) as client:
        d = client.get("/api/community/coop-a").json()
        assert d["events"] and all(e["kind"] != "world.cycle" for e in d["events"])
        assert client.get("/api/community/nobody").status_code == 404


def test_stream_sends_snapshots():
    with TestClient(create_app(World(Params(seed=0)), autostart=False)) as client:
        with client.stream("GET", "/stream?interval=0.01&limit=2") as r:
            frames = [line for line in r.iter_lines() if line.startswith("data: ")]
    assert frames and json.loads(frames[0][6:])["run"]["cycle"] == 0


def test_snapshot_stays_bounded_over_a_long_run():
    w = World(Params(seed=1, verify=False), hub=Hub(ring=200))
    state = {"world": w, "running": False, "speed": 4, "reason": None, "rss_limit": 1}
    sizes = []
    for n in (500, 3000):
        w.run(n - w.cycle)
        sizes.append(len(json.dumps(snapshot(state))))
    assert all(len(r) <= 200 for r in w.hub._rings.values())
    assert sizes[1] < sizes[0] * 1.5, sizes


def test_dashboard_separates_real_money_from_credits():
    w = World(Params(seed=0)).run(3)
    w.meter.real_ceiling = 10**9
    from commons.domain.compute import Usage
    w.meter.charge_usage("coop-a", "claude-haiku-4-5", Usage(input_tokens=1000), cycle=w.cycle, real=True)
    snap = snapshot({"world": w, "running": False, "speed": 4, "reason": None, "rss_limit": 1})
    assert snap["money"]["currency"] == "SIM"
    assert snap["money"]["real"] == {"capital_in": 1000, "revenue": 0, "api_spend": 1000, "fees": 0}
    assert snap["ledger"]["flows"].get("api", 0) == 0  # the real bill isn't mixed into credit flows
