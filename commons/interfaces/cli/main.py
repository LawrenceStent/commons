"""`commons`: one command for every tool. Each subcommand runs its module with the remaining arguments.

    uv run commons run ...         a live society (interfaces/cli/live.py)
    uv run commons sim ...         a scripted society (interfaces/cli/sim.py)
    uv run commons found ...       found a society from a brief, or approve its blueprints
    uv run commons approve ...     decide the gate's requests
    uv run commons rate ...        rate the work a society set aside for you
    uv run commons calibrate ...   check a grader or appraiser against its hand-labelled cases

`docs/COMMANDS.md` documents every option.
"""

import runpy
import sys

COMMANDS = {
    "run": "commons.interfaces.cli.live",
    "sim": "commons.interfaces.cli.sim",
    "found": "commons.interfaces.cli.found",
    "approve": "commons.interfaces.cli.approve",
    "rate": "commons.interfaces.cli.rate",
    "calibrate": "commons.interfaces.cli.calibrate",
}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print(__doc__.strip())
        sys.exit(0 if not argv or argv[0] in ("-h", "--help") else f"unknown command {argv[0]!r}")
    sys.argv = [f"commons {argv[0]}", *argv[1:]]
    runpy.run_module(COMMANDS[argv[0]], run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
