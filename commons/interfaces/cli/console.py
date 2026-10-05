"""The dashboard on a scripted society: every component live, with controls (pause, step, speed, kill-switch).

    uv run commons console [--pack NAME] [--seed N] [--port 8000]
    uv run commons console --open NAME        a saved society (commons list), read only; or pick one on the page

To watch a live run instead, use `commons run --serve`.
"""

import argparse
import sys

import uvicorn

from commons.application.society import Params, World
from commons.domain.pack import load as load_pack
from commons.application import registry
from commons.interfaces.console.app import create_app, open_saved


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons console", description="the dashboard on a scripted society")
    ap.add_argument("--pack", default=None, help="which pack (default earn_online)")
    ap.add_argument("--seed", type=int, default=0, help="random seed")
    ap.add_argument("--port", type=int, default=8000, help="where it listens (http://localhost:PORT)")
    ap.add_argument("--open", metavar="NAME", help="open a saved society to look at, read only (commons list shows them)")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    pack = load_pack(a.pack)
    app = create_app(World(Params(**{**pack.params, "seed": a.seed}), pack=pack), autostart=not a.open)
    if a.open:
        save = registry.folder_of(a.open) / registry.STATE / "society.save"
        if not save.exists():
            sys.exit(f"no saved society called {a.open} (commons list shows them)")
        app.state.console.open_saved(a.open, open_saved(save))
    print(f"dashboard: http://localhost:{a.port} (Ctrl-C to stop)" + (f" · {a.open}, read only" if a.open else ""))
    uvicorn.run(app, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
