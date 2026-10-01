"""What the machine is doing: this process's memory and CPU, free memory, and LM Studio.

Sampling is cheap (a few syscalls). The LM Studio check is one local HTTP request with a
short timeout, cached, so a stopped server costs nothing noticeable.
"""

from __future__ import annotations

import json
import time
import urllib.request

import psutil

LMSTUDIO = "http://localhost:1234/api/v0/models"

_proc = psutil.Process()
_proc.cpu_percent()  # the first call only sets the baseline
_lm_cache: tuple[float, dict] = (0.0, {})


def lmstudio(max_age: float = 10.0) -> dict:
    """{"app": running?, "server": reachable?, "loaded": [model ids]}."""
    global _lm_cache
    at, cached = _lm_cache
    if cached and time.monotonic() - at < max_age:
        return cached
    app = any((p.info["name"] or "").startswith("LM Studio") for p in psutil.process_iter(["name"]))
    out = {"app": app, "server": False, "loaded": []}
    if app:
        try:
            with urllib.request.urlopen(LMSTUDIO, timeout=0.3) as r:
                models = json.load(r).get("data", [])
            out["server"] = True
            out["loaded"] = [m["id"] for m in models if m.get("state") == "loaded"]
        except (OSError, ValueError):
            pass
    _lm_cache = (time.monotonic(), out)
    return out


def sample() -> dict:
    vm = psutil.virtual_memory()
    return {
        "rss": _proc.memory_info().rss,
        "cpu": _proc.cpu_percent(),
        "sys_available": vm.available,
        "sys_total": vm.total,
        "sys_percent": vm.percent,
        "lmstudio": lmstudio(),
    }
