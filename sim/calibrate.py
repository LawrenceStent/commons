"""Old entry point, kept working: `python -m sim.calibrate` is now `uv run commons calibrate` (see docs/COMMANDS.md)."""

import runpy
import sys

print("note: this command moved: uv run commons calibrate ...", file=sys.stderr)
runpy.run_module("commons.interfaces.cli.calibrate", run_name="__main__", alter_sys=True)
