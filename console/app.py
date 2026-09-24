"""The console: watch the society, pause it, and (from Phase 2) work the gate queue.

    uv run uvicorn console.app:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from sim.engine import Params, World

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Commons Console</title>
<script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js"></script>
<style>
:root { --bg:#EEF1F0; --fg:#16202B; --muted:#5D6B70; --rule:#D2DAD8; --card:#fff; --accent:#1B6B5E; --bad:#9E4629; }
@media (prefers-color-scheme: dark) { :root { --bg:#0F1518; --fg:#DDE5E3; --muted:#93A2A4; --rule:#26312F; --card:#151D20; --accent:#4CB8A0; --bad:#D4805A; } }
body { background:var(--bg); color:var(--fg); font:14px/1.5 ui-sans-serif,-apple-system,sans-serif; margin:0; padding:20px 16px; }
main { max-width:1100px; margin:0 auto; display:grid; gap:18px; }
h1, h2 { font-family:ui-monospace,Menlo,monospace; margin:0; } h1 { font-size:20px; } h2 { font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin-bottom:8px; }
section { background:var(--card); border:1px solid var(--rule); padding:14px 16px; overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:5px 10px; border-bottom:1px solid var(--rule); white-space:nowrap; }
th { font-size:11px; color:var(--muted); font-weight:600; }
.num { text-align:right; font-family:ui-monospace,Menlo,monospace; }
.bad { color:var(--bad); } .ok { color:var(--accent); } .muted { color:var(--muted); }
.bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
button { font:inherit; padding:4px 12px; border:1px solid var(--rule); background:var(--card); color:var(--fg); cursor:pointer; }
pre { margin:0; font:12px/1.55 ui-monospace,Menlo,monospace; }
</style></head>
<body><main>
  <div class="bar"><h1>Commons</h1>
    <span id="status" hx-get="/partials/status" hx-trigger="load, every 1s"></span>
    <button hx-post="/control/pause" hx-target="#status">pause</button>
    <button hx-post="/control/resume" hx-target="#status">resume</button>
    <button hx-post="/control/step" hx-target="#status">step</button>
  </div>
  <section><h2>Communities</h2><div hx-get="/partials/communities" hx-trigger="load, every 1s"></div></section>
  <section><h2>Gate queue</h2><div hx-get="/partials/gate" hx-trigger="load, every 2s"></div></section>
  <section><h2>Bus tail</h2><div hx-get="/partials/bus" hx-trigger="load, every 1s"></div></section>
</main></body></html>"""


def create_app(world: World | None = None, cycles_per_second: float = 4.0, autostart: bool = True) -> FastAPI:
    state = {"world": world or World(Params(seed=0)), "running": autostart}

    async def driver():
        while True:
            if state["running"]:
                state["world"].step()
            await asyncio.sleep(1 / cycles_per_second)

    @contextlib.asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(driver())
        yield
        task.cancel()

    app = FastAPI(title="Commons console", lifespan=lifespan)
    app.state.console = state

    def status() -> str:
        w = state["world"]
        s = "running" if state["running"] else "paused"
        return (f'<span class="muted">cycle {w.cycle} · {s} · jobs {w.jobs_done}/{w.jobs_done + w.jobs_failed} · '
                f'treasury ${w.ledger.balance("treasury") / 1e6:,.3f}</span>')

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return PAGE

    @app.get("/partials/status", response_class=HTMLResponse)
    async def partial_status():
        return status()

    @app.post("/control/{action}", response_class=HTMLResponse)
    async def control(action: str):
        if action == "pause":
            state["running"] = False
        elif action == "resume":
            state["running"] = True
        elif action == "step":
            state["world"].step()
        return status()

    @app.get("/partials/communities", response_class=HTMLResponse)
    async def partial_communities():
        w = state["world"]
        rows = []
        for name, c in w.communities.items():
            h = w.history[name][-1] if w.history[name] else None
            if h is None:
                continue
            cls = "bad" if h.standing < 0.35 else "ok" if h.standing > 0.7 else ""
            rows.append(
                f"<tr><td>{html.escape(name)}</td><td class='muted'>{c.strategy.name}</td>"
                f"<td class='muted'>{', '.join(sorted(c.capabilities))}</td>"
                f"<td class='num'>{h.thinking}/{c.members}</td>"
                f"<td class='num'>${h.purse / 1e6:,.3f}</td>"
                f"<td class='num {cls}'>{h.standing:.3f}</td>"
                f"<td class='num'>{h.allowance}</td>"
                f"<td class='num'>{sum(s.won for s in w.history[name])}</td>"
                f"<td class='num'>{sum(s.delivered_ok for s in w.history[name])}</td></tr>"
            )
        return ("<table><tr><th>community</th><th>strategy</th><th>capabilities</th><th class='num'>thinking</th>"
                "<th class='num'>purse</th><th class='num'>standing</th><th class='num'>bus/cycle</th>"
                "<th class='num'>won</th><th class='num'>delivered</th></tr>" + "".join(rows) + "</table>")

    @app.get("/partials/bus", response_class=HTMLResponse)
    async def partial_bus():
        lines = []
        for env in list(state["world"].bus.recent)[-25:][::-1]:
            body = ", ".join(f"{k}={v}" for k, v in env.body.items() if k != "artifact")
            lines.append(f"{env.cycle:>6}  {env.sender:<10} {env.family}.{env.verb:<9} {body}")
        return "<pre>" + html.escape("\n".join(lines) or "(quiet)") + "</pre>"

    @app.get("/partials/gate", response_class=HTMLResponse)
    async def partial_gate():
        return "<p class='muted'>No pending requests. Nothing in Phase 0 touches the outside world.</p>"

    return app


app = create_app()
