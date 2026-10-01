"""Old entry point, kept working: `python -m sim.approve` is now `uv run commons approve` (see docs/COMMANDS.md)."""

import runpy
import sys

print("note: this command moved: uv run commons approve ...", file=sys.stderr)
runpy.run_module("commons.interfaces.cli.approve", run_name="__main__", alter_sys=True)
