from fastapi.testclient import TestClient

from console.app import create_app
from sim.engine import Params, World


def test_console_renders_and_controls():
    app = create_app(World(Params(seed=0)), autostart=False)
    with TestClient(app) as client:
        assert "htmx" in client.get("/").text
        assert "cycle 0" in client.get("/partials/status").text
        assert "cycle 1" in client.post("/control/step").text
        page = client.get("/partials/communities").text
        assert "defector" in page and "coop-a" in page
        assert "contract." in client.get("/partials/bus").text
        assert "No pending" in client.get("/partials/gate").text
        assert "running" in client.post("/control/resume").text
        assert "paused" in client.post("/control/pause").text
