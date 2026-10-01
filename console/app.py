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
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from console import host
from sim.engine import Params, World
from sim.status import LIVE_CONTRACT, ContractStatus, GoalStatus, JobStatus, ProposalStatus, RequestStatus
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
            "efficiency": w.efficiency(name),
            "rate_limited": w.bus.rejected.get(name, 0),
            "royalties": w.royalties_paid.get(name, 0),
            "purse_series": _downsample([[e.cycle, e.fields["communities"][name]["purse"]] for e in cycles
                                         if name in e.fields["communities"]]),
            "parent": c.parent, "dissolved": c.dissolved,
        })

    names = list(w.communities)
    trust = {o: {s: (None if o == s else round(w.rep.trust(o, s), 3)) for s in names} for o in names}

    closed = tuple(s for s in ContractStatus if s not in LIVE_CONTRACT)
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
        "gate": {"web": bool(w.web), "policy": asdict(w.gate.policy), "groups": w.gate.groups(),
                 "standing": sorted([c, h] for c, h in w.gate.standing),
                 "recent": [{"id": r.id, "coop": r.coop, "tool": r.tool, "target": r.target, "status": r.status,
                             "result": r.result, "cycle": r.cycle} for r in list(w.gate.requests.values())[-20:]
                            if r.status != RequestStatus.PENDING][::-1]},
        "society": {"pack": w.pack.title, "economy": w.params.economy, "scorecard": w.scorecard,
                    "grants": w.ledger.balance("grants") if w.params.economy == "grant" else None,
                    "grant_budget": w.params.grant_budget},
        "treasury_series": _downsample([[e.cycle, e.fields["treasury"]] for e in cycles]),
        "communities": communities,
        "reputation": {"names": names, "trust": trust,
                       "attests": [_ev(e) for e in hub.recent("reputation.attest", n=12)][::-1]},
        "market": {"recent": [_ev(e) for e in hub.recent("market.job", n=60) if e.fields["stage"] != "posted"][-15:][::-1],
                   "done": w.jobs_done, "failed": w.jobs_failed, "expired": w.jobs_expired,
                   "board": sum(j.status == JobStatus.OPEN for j in w.jobs.values()),
                   "in_progress": sum(j.status == JobStatus.CLAIMED for j in w.jobs.values()),
                   "reward": w.params.job_reward},
        "contracts": {"recent": contracts[-15:][::-1], "stages": Counter(c["stage"] for c in contracts),
                      "window": len(contracts),
                      "live": Counter(c.status for c in w.contracts.values() if c.status in (ContractStatus.OPEN, ContractStatus.AWARDED, ContractStatus.DELIVERED))},
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
                     for x in w.proposals.values() if x.status == ProposalStatus.OPEN],
            "living": sum(not c.dissolved for c in w.communities.values()),
            "members": sum(c.members for c in w.communities.values()),
            "limits": {"members": w.params.max_members, "communities": w.params.max_communities},
        },
        "activity": [asdict(e) for e in w.activity.recent(150)][::-1],
        "plans": {
            "goals": [{"community": n, "id": g.id, "title": g.title, "status": g.status, "progress": round(g.progress, 3),
                       "created": g.created, "updated": g.updated, "outcome": g.outcome,
                       "steps": [{"text": s.text, "done": s.done, "note": s.note} for s in g.steps]}
                      for n, p in w.plans.items() for g in sorted(p.goals.values(), key=lambda g: (g.status != GoalStatus.ACTIVE, -g.updated))],
            "ideas": [{"community": n, **asdict(i)} for n, p in w.plans.items() for i in p.ideas][-40:][::-1],
            "ventures": [{"id": v.id, "proposer": v.proposer, "title": v.title, "pitch": v.pitch, "status": v.status,
                          "score": v.score, "reward": v.reward, "reason": v.reason, "job_id": v.job_id, "cycle": v.cycle,
                          "parts": [c for c, _, _ in v.parts]} for v in list(w.ventures.values())[-30:]][::-1],
            "jobs": [{"id": j.id, "title": j.title, "prime": j.prime, "deadline": j.deadline, "reward": j.reward,
                      "awaiting_grade": j.id in w.awaiting_grade,
                      "parts": [{"capability": cap, "done": part.artifact is not None,
                                 "state": "done" if part.artifact is not None else next(
                                     (c.status for c in w.contracts.values()
                                      if c.job_id == j.id and c.capability == cap and c.status in (ContractStatus.OPEN, ContractStatus.AWARDED, ContractStatus.DELIVERED)), "open")}
                                for cap, part in sorted(j.parts.items())]}
                     for j in w.jobs.values() if j.status == JobStatus.CLAIMED],
        },
        "operator": {
            "enabled": w.operator.root is not None, "folder": str(w.operator.root) if w.operator.root else None,
            "errors": list(w.operator.errors),
            "coops": [{"name": n, "directives": v.directives, "own": _own_directives(w, n), "limits": v.limits.describe(),
                       "context": [name for name, _ in v.context], "runtime": v.runtime}
                      for n in list(w.communities) for v in [w.operator.view(n)]],
            "all": _own_directives(w, None),
        },
        "knowledge": [{"id": pb.id, "author": pb.author, "capability": pb.capability, "title": pb.title, "uses": pb.uses}
                      for pb in w.library.values()],
        "llm": {"recent": llm[-10:][::-1], "calls": hub.counts["llm.call"],
                "cost": sum(c.get("cost", 0) for c in llm)},
        "grader": {"recent": grades[-10:][::-1], "count": hub.counts["grader.grade"]},
        "host": {**(hosts[-1].fields if hosts else {}),
                 "rss_series": _downsample([[round(e.at), e.fields["rss"]] for e in hosts])},
        "events": dict(hub.counts),
    }


def _own_directives(w: World, coop: str | None) -> str:
    """The text of one directives file as written (all.md, or coops/<name>.md), for editing."""
    if not w.operator.root:
        return ""
    p = w.operator.root / ("all.md" if coop is None else f"coops/{coop}.md")
    return p.read_text() if p.exists() else ""


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
    """`stop_at` pauses the run at that cycle. The world steps in a worker thread and snapshots take the
    world's lock, so slow (LLM) cycles never freeze the page and a snapshot never sees a half-made change."""
    state = {"world": world or World(Params(seed=0)), "running": autostart, "speed": cycles_per_second,
             "reason": None, "rss_limit": rss_limit, "stop_at": stop_at}

    def pause(reason: str | None) -> None:
        state["running"], state["reason"] = False, reason

    def step() -> None:
        # the world takes its own lock: for the whole cycle normally, per action with parallel turns,
        # so with parallel turns the page updates while communities are still thinking
        try:
            state["world"].step()
        except KillSwitch as e:
            pause(f"kill-switch: {e}")
        except Exception as e:  # a crash pauses the run and says why, rather than killing the driver
            pause(f"the world raised {type(e).__name__}: {e}")
        if state["stop_at"] and state["world"].cycle >= state["stop_at"]:
            pause(f"reached the cycle limit ({state['stop_at']})")

    def locked(fn, *a):
        with state["world"].lock:
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
                    "activity": [asdict(e) for e in w.activity.recent(80, community=name)][::-1],
                    "events": community_detail(w, name)}

        return await asyncio.to_thread(locked, detail)

    @app.post("/api/operator")
    async def api_operator(request: Request):
        """Set directives for one co-op (`coop`) or for all (`coop` null). They apply from the next turn."""
        body = await request.json()
        w = state["world"]
        coop = body.get("coop")
        if coop is not None and coop not in w.communities:
            return JSONResponse({"error": f"no co-op {coop}"}, status_code=404)
        try:
            def apply():
                w.operator.set_directives(coop, str(body.get("directives", "")))
                if w.operator.reload():
                    w.hub.emit("operator.update", w.cycle, coops=sorted(w.operator.views), errors=w.operator.errors)
            await asyncio.to_thread(locked, apply)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"ok": True, "errors": w.operator.errors}

    @app.post("/api/gate")
    async def api_gate(request: Request):
        """Approve or deny gate requests (`ids`), optionally `always` (a standing approval for co-op and host), or
        `revoke` a standing approval ({coop, host}). Approved requests run at the start of the next cycle."""
        body = await request.json()
        w = state["world"]
        if "revoke" in body:
            rv = body["revoke"] or {}
            ok = await asyncio.to_thread(locked, w.gate.revoke, str(rv.get("coop")), str(rv.get("host")))
            return {"ok": ok}
        ids = [str(i) for i in body.get("ids", [])][:500]
        done = await asyncio.to_thread(w.gate_decide, ids, bool(body.get("approve")), bool(body.get("always")),
                                       str(body.get("reason", ""))[:200])
        return {"ok": True, "decided": [r.id for r in done]}

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
