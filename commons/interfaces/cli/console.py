"""The dashboard on a scripted society: every component live, with controls (pause, step, speed, kill-switch).

    uv run commons console [--pack NAME] [--seed N] [--port 8000]

To watch a live run instead, use `commons run --serve`.
"""

import argparse

import uvicorn

from commons.application.society import Params, World
from commons.domain.pack import load as load_pack
from commons.interfaces.console.app import create_app


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons console", description="the dashboard on a scripted society")
    ap.add_argument("--pack", default=None, help="which pack (default earn_online)")
    ap.add_argument("--seed", type=int, default=0, help="random seed")
    ap.add_argument("--port", type=int, default=8000, help="where it listens (http://localhost:PORT)")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    pack = load_pack(a.pack)
    print(f"dashboard: http://localhost:{a.port} (Ctrl-C to stop)")
    uvicorn.run(create_app(World(Params(**{**pack.params, "seed": a.seed}), pack=pack)), port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
