"""The console: a live dashboard of every component, with run controls.

    uv run commons console          (or: uv run uvicorn commons.interfaces.console.app:app)

One Server-Sent Events stream (`/stream`) pushes a snapshot of the whole society about
twice a second; the page renders every panel from it. Snapshots are built from the
world's current state plus the telemetry hub's bounded rings, so their size doesn't grow
with the length of the run.

Guards: the meter's kill-switch pauses the run, and so does this process's RSS crossing
`rss_limit`. Either way the dashboard shows why.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from commons.application import queries
from commons.application.queries import community_detail
from commons.application.society import Params, World
from commons.domain import events as ev
from commons.interfaces.console.runner import Runner

PAGE = (Path(__file__).parent / "dashboard.html").read_text()


def snapshot(state: dict) -> dict:
    """The page's data: a world and its run controls (see commons/application/queries.py)."""
    return queries.snapshot(state["world"], state)


def create_app(world: World | None = None, cycles_per_second: float = 4.0, autostart: bool = True,
               rss_limit: int = 2 * 1024**3, host_every: float = 2.0, stop_at: int | None = None) -> FastAPI:
    """`stop_at` pauses the run at that cycle."""
    run = Runner(world or World(Params(seed=0)), cycles_per_second, autostart, rss_limit, host_every, stop_at)

    @contextlib.asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(run.drive())
        yield
        task.cancel()

    app = FastAPI(title="Commons console", lifespan=lifespan)
    app.state.console = run
    routes = Routes(run)
    app.add_api_route("/", routes.index, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/api/snapshot", routes.snapshot, methods=["GET"])
    app.add_api_route("/api/community/{name}", routes.community, methods=["GET"])
    app.add_api_route("/api/operator", routes.operator, methods=["POST"])
    app.add_api_route("/api/gate", routes.gate, methods=["POST"])
    app.add_api_route("/stream", routes.stream, methods=["GET"])
    app.add_api_route("/control/{action}", routes.control, methods=["POST"])
    return app


class Routes:
    """What each address does; the page's data comes from commons/application/queries.py."""

    def __init__(self, run: Runner):
        self.run = run

    async def index(self):
        return PAGE

    async def snapshot(self):
        return JSONResponse(await self.run.snapshot())

    async def community(self, name: str):
        if name not in self.run.world.communities:
            return JSONResponse({"error": f"no community {name}"}, status_code=404)
        return await asyncio.to_thread(self.run.locked, queries.community_view, self.run.world, name)

    async def operator(self, request: Request):
        """Set directives for one co-op (`coop`) or for all (`coop` null). They apply from the next turn."""
        body, w = await request.json(), self.run.world
        coop = body.get("coop")
        if coop is not None and coop not in w.communities:
            return JSONResponse({"error": f"no co-op {coop}"}, status_code=404)

        def apply():
            w.operator.set_directives(coop, str(body.get("directives", "")))
            if w.operator.reload():
                w.events.publish(ev.OperatorReloaded(tuple(sorted(w.operator.views)), tuple(w.operator.errors)))
        try:
            await asyncio.to_thread(self.run.locked, apply)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"ok": True, "errors": w.operator.errors}

    async def gate(self, request: Request):
        """Approve or deny gate requests (`ids`), optionally `always` (a standing approval for co-op and host), or
        `revoke` a standing approval ({coop, host}). Approved requests run at the start of the next cycle."""
        body, w, run = await request.json(), self.run.world, self.run
        if "revoke" in body:
            rv = body["revoke"] or {}
            return {"ok": await asyncio.to_thread(run.locked, w.gate.revoke, str(rv.get("coop")), str(rv.get("host")))}
        ids = [str(i) for i in body.get("ids", [])][:500]
        done = await asyncio.to_thread(w.web_desk.decide, ids, bool(body.get("approve")), bool(body.get("always")),
                                       str(body.get("reason", ""))[:200])
        return {"ok": True, "decided": [r.id for r in done]}

    async def stream(self, request: Request, interval: float = 0.5, limit: int | None = None):
        async def gen():
            sent, last_cycle = 0, None
            while limit is None or sent < limit:
                if await request.is_disconnected():
                    break
                snap = await self.run.snapshot()
                # while paused, only resend every few seconds so host stats stay fresh
                if snap["run"]["cycle"] != last_cycle or sent % 6 == 0:
                    yield f"data: {json.dumps(snap, separators=(',', ':'))}\n\n"
                    last_cycle = snap["run"]["cycle"]
                sent += 1
                await asyncio.sleep(interval)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def control(self, action: str, value: float | None = None):
        if action == "step":
            await asyncio.to_thread(self.run.step)
        elif error := self.run.control(action, value):
            return JSONResponse({"error": error}, status_code=409 if "kill-switch" in error else 400)
        return (await self.run.snapshot())["run"]


__all__ = ["create_app", "snapshot", "community_detail", "app"]

app = create_app()
