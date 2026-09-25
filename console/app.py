"""The console: a live dashboard of every component, with run controls.

    uv run uvicorn console.app:app

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
import threading
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from console import host
from sim.engine import Params, World
from substrate.ledger import purse
from substrate.meter import KillSwitch

PAGE = (Path(__file__).parent / "dashboard.html").read_text()
SERIES_POINTS = 120  # points per sparkline, however long the run


def _downsample(xs: list, n: int = SERIES_POINTS) -> list:
    if len(xs) <= n:
        return xs
    step = len(xs) / n
    return [xs[int(i * step)] for i in range(n - 1)] + [xs[-1]]


def _ev(e) -> dict:
    return {**e.fields, "seq": e.seq, "kind": e.kind, "cycle": e.cycle}


def snapshot(state: dict) -> dict:
    w: World = state["world"]
    hub = w.hub
    cycles = hub.recent("world.cycle", n=hub.ring)
    last = cycles[-1].fields if cycles else {"communities": {}, "bus_sent": {}}
    prev = cycles[-2].fields if len(cycles) > 1 else {"bus_sent": {}}

    communities = []
    for name, c in w.communities.items():
        now = last["communities"].get(name, {})
        communities.append({
            "name": name, "strategy": c.strategy.name, "capabilities": sorted(c.capabilities),
            "members": c.members, **now,
            "won_total": sum(s.won for s in w.history[name]),
            "ok_total": sum(s.delivered_ok for s in w.history[name]),
            "compute": w.meter.by_community.get(name, 0),
            "rate_limited": w.bus.rejected.get(name, 0),
            "royalties": w.royalties_paid.get(name, 0),
            "purse_series": _downsample([[e.cycle, e.fields["communities"][name]["purse"]] for e in cycles
                                         if name in e.fields["communities"]]),
            "parent": c.parent, "dissolved": c.dissolved,
        })

    names = list(w.communities)
    trust = {o: {s: (None if o == s else round(w.rep.trust(o, s), 3)) for s in names} for o in names}

    closed = ("accepted", "rejected", "failed", "defaulted", "expired", "withdrawn")
    contracts = [_ev(e) for e in hub.recent("contract.stage", n=hub.ring) if e.fields["stage"] in closed]
    posts = [_ev(e) for e in hub.recent("ledger.post", n=hub.ring)]
    flows: Counter[str] = Counter()
    for p in posts:
        if p["currency"] == w.ledger.currency:  # never add real dollars and credits together
            flows[p["type"]] += sum(n for _, n in p["legs"] if n > 0)

    llm = [_ev(e) for e in hub.recent("llm.call", n=hub.ring)]
    grades = [_ev(e) for e in hub.recent("grader.grade", n=hub.ring)]
    hosts = hub.recent("host.sample", n=hub.ring)

    return {
        "run": {
            "cycle": w.cycle, "running": state["running"], "speed": state["speed"], "pause_reason": state["reason"],
            "seed": w.params.seed, "reputation": w.params.reputation,
            "jobs_done": w.jobs_done, "jobs_failed": w.jobs_failed,
            "treasury": w.ledger.balance("treasury"), "halted": w.meter.halted,
            "spent_today": w.meter._spent_today, "ceiling": w.meter.daily_ceiling,
            "rss_limit": state["rss_limit"],
        },
        "money": {"currency": w.ledger.currency, "real": w.ledger.real(),
                  "real_spent_today": w.meter.real_spent_today, "real_ceiling": w.meter.real_ceiling},
        "treasury_series": _downsample([[e.cycle, e.fields["treasury"]] for e in cycles]),
        "communities": communities,
        "reputation": {"names": names, "trust": trust,
                       "attests": [_ev(e) for e in hub.recent("reputation.attest", n=12)][::-1]},
        "market": {"recent": [_ev(e) for e in hub.recent("market.job", n=60) if e.fields["stage"] != "posted"][-15:][::-1],
                   "done": w.jobs_done, "failed": w.jobs_failed, "expired": w.jobs_expired,
                   "board": sum(j.status == "open" for j in w.jobs.values()),
                   "in_progress": sum(j.status == "claimed" for j in w.jobs.values()),
                   "reward": w.params.job_reward},
        "contracts": {"recent": contracts[-15:][::-1], "stages": Counter(c["stage"] for c in contracts),
                      "window": len(contracts),
                      "live": Counter(c.status for c in w.contracts.values() if c.status in ("open", "awarded", "delivered"))},
        "ledger": {"recent": posts[-15:][::-1], "flows": flows, "window": len(posts),
                   "compute": w.ledger.balance("compute"), "market": w.ledger.balance("market")},
        "bus": {
            "sent": last["bus_sent"],
            "last_cycle": {f: n - prev["bus_sent"].get(f, 0) for f, n in last["bus_sent"].items()},
            "rate_limited": dict(w.bus.rejected),
            "tail": [_ev(e) for e in hub.recent("bus.publish", n=20)][::-1],
        },
        "population": {
            "recent": [_ev(e) for e in hub.recent("population.", n=15)][::-1],
            "open": [{"id": x.id, "kind": x.kind, "proposer": x.proposer, "detail": x.role or x.target, "deadline": x.deadline}
                     for x in w.proposals.values() if x.status == "open"],
            "living": sum(not c.dissolved for c in w.communities.values()),
            "members": sum(c.members for c in w.communities.values()),
            "limits": {"members": w.params.max_members, "communities": w.params.max_communities},
        },
        "knowledge": [{"id": pb.id, "author": pb.author, "capability": pb.capability, "title": pb.title, "uses": pb.uses}
                      for pb in w.library.values()],
        "llm": {"recent": llm[-10:][::-1], "calls": hub.counts["llm.call"],
                "cost": sum(c.get("cost", 0) for c in llm)},
        "grader": {"recent": grades[-10:][::-1], "count": hub.counts["grader.grade"]},
        "gate": [],
        "host": {**(hosts[-1].fields if hosts else {}),
                 "rss_series": _downsample([[round(e.at), e.fields["rss"]] for e in hosts])},
        "events": dict(hub.counts),
    }


def community_detail(w: World, name: str, n: int = 60) -> list[dict]:
    """Recent events that involve `name` in any field."""
    def involves(v) -> bool:
        if v == name:
            return True
        if isinstance(v, dict):
            return name in v or any(involves(x) for x in v.values())
        if isinstance(v, (list, tuple)):
            return any(involves(x) for x in v)
        return False

    hits = [e for e in w.hub.recent(n=w.hub.ring) if e.kind != "world.cycle" and involves(e.fields)]
    return [_ev(e) for e in hits[-n:][::-1]]


def create_app(world: World | None = None, cycles_per_second: float = 4.0, autostart: bool = True,
               rss_limit: int = 2 * 1024**3, host_every: float = 2.0, stop_at: int | None = None) -> FastAPI:
    """`stop_at` pauses the run at that cycle. The world steps in a worker thread under a lock, so
    slow (LLM) cycles never freeze the page, and a snapshot never sees a half-finished cycle."""
    state = {"world": world or World(Params(seed=0)), "running": autostart, "speed": cycles_per_second,
             "reason": None, "rss_limit": rss_limit, "stop_at": stop_at}
    lock = threading.Lock()

    def pause(reason: str | None) -> None:
        state["running"], state["reason"] = False, reason

    def step() -> None:
        with lock:
            try:
                state["world"].step()
            except KillSwitch as e:
                pause(f"kill-switch: {e}")
            except Exception as e:  # a crash pauses the run and says why, rather than killing the driver
                pause(f"the world raised {type(e).__name__}: {e}")
        if state["stop_at"] and state["world"].cycle >= state["stop_at"]:
            pause(f"reached the cycle limit ({state['stop_at']})")

    def locked(fn, *a):
        with lock:
            return fn(*a)

    async def snap() -> dict:
        return await asyncio.to_thread(locked, snapshot, state)

    def sample_host() -> None:
        s = host.sample()
        w = state["world"]
        w.hub.emit("host.sample", w.cycle, **s)
        if s["rss"] > state["rss_limit"] and state["running"]:
            pause(f"memory guard: process RSS {s['rss'] / 2**20:,.0f} MB over {state['rss_limit'] / 2**20:,.0f} MB")
            w.hub.emit("host.guard", w.cycle, rss=s["rss"], limit=state["rss_limit"])

    async def driver():
        since_host = host_every
        while True:
            if state["running"]:
                await asyncio.to_thread(step)
            since_host += 1 / state["speed"]
            if since_host >= host_every:
                since_host = 0.0
                await asyncio.to_thread(sample_host)
            await asyncio.sleep(1 / state["speed"])

    @contextlib.asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(driver())
        yield
        task.cancel()

    app = FastAPI(title="Commons console", lifespan=lifespan)
    app.state.console = state

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return PAGE

    @app.get("/api/snapshot")
    async def api_snapshot():
        return JSONResponse(await snap())

    @app.get("/api/community/{name}")
    async def api_community(name: str):
        w = state["world"]
        if name not in w.communities:
            return JSONResponse({"error": f"no community {name}"}, status_code=404)
        def detail():
            c = w.communities[name]
            return {"name": name, "charter": c.charter, "purse": w.ledger.balance(purse(name)),
                    "strategy": c.strategy.name,
                    "journal": list(w.journal[name]), "inbox": [e.__dict__ for e in w.inbox[name]],
                    "transcripts": list(w.transcripts.get(name, [])),
                    "events": community_detail(w, name)}

        return await asyncio.to_thread(locked, detail)

    @app.get("/stream")
    async def stream(request: Request, interval: float = 0.5, limit: int | None = None):
        async def gen():
            sent, last_cycle = 0, None
            while limit is None or sent < limit:
                if await request.is_disconnected():
                    break
                snap_ = await snap()
                # while paused, only resend every few seconds so host stats stay fresh
                if snap_["run"]["cycle"] != last_cycle or sent % 6 == 0:
                    yield f"data: {json.dumps(snap_, separators=(',', ':'))}\n\n"
                    last_cycle = snap_["run"]["cycle"]
                sent += 1
                await asyncio.sleep(interval)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/control/{action}")
    async def control(action: str, value: float | None = None):
        w = state["world"]
        if action == "pause":
            pause("paused from the dashboard")
        elif action == "resume":
            if w.meter.halted:
                return JSONResponse({"error": "the kill-switch is on; reset it first"}, status_code=409)
            state["running"], state["reason"] = True, None
        elif action == "step":
            await asyncio.to_thread(step)
        elif action == "speed" and value:
            state["speed"] = min(50.0, max(0.25, value))
        elif action == "kill":
            w.meter.halt("pulled from the dashboard", w.cycle)
            pause("kill-switch pulled from the dashboard")
        elif action == "reset-kill":
            w.meter.reset()
            state["reason"] = None
        else:
            return JSONResponse({"error": f"unknown action {action}"}, status_code=400)
        return (await snap())["run"]

    return app


app = create_app()
