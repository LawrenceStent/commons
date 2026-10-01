"""Old entry point, kept working: `python -m sim.found` is now `uv run commons found` (see docs/COMMANDS.md)."""

import runpy
import sys

print("note: this command moved: uv run commons found ...", file=sys.stderr)
runpy.run_module("commons.interfaces.cli.found", run_name="__main__", alter_sys=True)
