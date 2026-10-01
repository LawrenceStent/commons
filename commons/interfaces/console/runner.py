"""The dashboard's run controls: a driver that steps the world in a worker thread, the speed, pausing (by you, the
kill-switch, a crash, the cycle limit, or the memory guard), and host sampling. Snapshots take the world's lock, so a
slow (LLM) cycle never freezes the page and a snapshot never sees a half-made change."""

from __future__ import annotations

import asyncio
from typing import Any

from commons.application import queries
from commons.application.society import World
from commons.interfaces.console import host
from commons.substrate.meter import KillSwitch


class Runner:
    def __init__(self, world: World, speed: float, running: bool, rss_limit: int, host_every: float,
                 stop_at: int | None):
        self.world, self.speed, self.running = world, speed, running
        self.reason: str | None = None
        self.rss_limit, self.host_every, self.stop_at = rss_limit, host_every, stop_at

    def view(self) -> dict[str, Any]:
        """The controls, as the dashboard shows them."""
        return {"world": self.world, "running": self.running, "speed": self.speed, "reason": self.reason,
                "rss_limit": self.rss_limit, "stop_at": self.stop_at}

    def pause(self, reason: str | None) -> None:
        self.running, self.reason = False, reason

    def resume(self) -> None:
        self.running, self.reason = True, None

    def step(self) -> None:
        # the world takes its own lock: for the whole cycle normally, per action with parallel turns,
        # so with parallel turns the page updates while communities are still thinking
        try:
            self.world.step()
        except KillSwitch as e:
            self.pause(f"kill-switch: {e}")
        except Exception as e:  # a crash pauses the run and says why, rather than killing the driver
            self.pause(f"the world raised {type(e).__name__}: {e}")
        if self.stop_at and self.world.cycle >= self.stop_at:
            self.pause(f"reached the cycle limit ({self.stop_at})")

    def locked(self, fn, *a):
        with self.world.lock:
            return fn(*a)

    async def snapshot(self) -> dict:
        return await asyncio.to_thread(self.locked, queries.snapshot, self.world, self.view())

    def sample_host(self) -> None:
        s = host.sample()
        w = self.world
        w.hub.emit("host.sample", w.cycle, **s)
        if s["rss"] > self.rss_limit and self.running:
            self.pause(f"memory guard: process RSS {s['rss'] / 2**20:,.0f} MB over {self.rss_limit / 2**20:,.0f} MB")
            w.hub.emit("host.guard", w.cycle, rss=s["rss"], limit=self.rss_limit)

    async def drive(self) -> None:
        since_host = self.host_every
        while True:
            if self.running:
                await asyncio.to_thread(self.step)
            since_host += 1 / self.speed
            if since_host >= self.host_every:
                since_host = 0.0
                await asyncio.to_thread(self.sample_host)
            await asyncio.sleep(1 / self.speed)

    def control(self, action: str, value: float | None) -> str | None:
        """A button on the page. An error message, or None."""
        w = self.world
        if action == "pause":
            self.pause("paused from the dashboard")
        elif action == "resume":
            if w.meter.halted:
                return "the kill-switch is on; reset it first"
            self.resume()
        elif action == "speed" and value:
            self.speed = min(50.0, max(0.25, value))
        elif action == "kill":
            w.meter.halt("pulled from the dashboard", w.cycle)
            self.pause("kill-switch pulled from the dashboard")
        elif action == "reset-kill":
            w.meter.reset()
            self.reason = None
        else:
            return f"unknown action {action}"
        return None
