"""Old entry point, kept working: `python -m sim.live` is now `uv run commons run` (see docs/COMMANDS.md)."""

import runpy
import sys

print("note: this command moved: uv run commons run ...", file=sys.stderr)
runpy.run_module("commons.interfaces.cli.live", run_name="__main__", alter_sys=True)
