"""`commons`: one command for every tool.

    uv run commons run ...         a live society, with LLM co-ops
    uv run commons tick ...        resume a saved society, play a few cycles, save it (scheduled forward tests)
    uv run commons tick-all ...    tick every unpaused society, one after another
    uv run commons list            every society on this machine; pause NAME / resume NAME / pace NAME MINUTES
    uv run commons sim ...         a scripted society (no models)
    uv run commons console ...     the dashboard on a scripted society
    uv run commons found ...       found a society from a brief, or approve its blueprints
    uv run commons approve ...     decide the gate's requests
    uv run commons rate ...        rate the work a society set aside for you
    uv run commons calibrate ...   check a grader or appraiser against its hand-labelled cases
    uv run commons metrics         architecture measurements (development)
    uv run commons golden ...      check or regenerate the golden master (development)

`uv run commons <command> --help` lists a command's options; docs/COMMANDS.md documents them all.
"""

import sys
from importlib import import_module

COMMANDS = {
    "run": "live", "sim": "sim", "console": "console", "found": "found", "approve": "approve", "rate": "rate",
    "calibrate": "calibrate", "metrics": "metrics", "golden": "golden", "tick": "tick",
    "tick-all": "tick:main_all", "list": "societies:main_list", "pause": "societies:main_pause",
    "resume": "societies:main_resume", "pace": "societies:main_pace",
}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    if argv[0] not in COMMANDS:
        print(__doc__.strip())
        sys.exit(f"unknown command {argv[0]!r}")
    module, _, function = COMMANDS[argv[0]].partition(":")
    getattr(import_module(f"commons.interfaces.cli.{module}"), function or "main")(argv[1:])


if __name__ == "__main__":
    main()
