"""Old entry point, kept working: `python -m sim` is now `uv run commons sim` (see docs/COMMANDS.md)."""

import runpy
import sys

print("note: this command moved: uv run commons sim ...", file=sys.stderr)
runpy.run_module("commons.interfaces.cli.sim", run_name="__main__", alter_sys=True)
