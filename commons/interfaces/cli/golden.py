"""The golden master (tests/golden): check that today's runs reproduce their recorded fixtures, or, after a behaviour
change you have approved, record new ones. For development, in a checkout of the repository.

    uv run commons golden                                   # check (the same as `uv run pytest -m golden`)
    uv run commons golden --update --approved "why"         # regenerate every fixture
"""

import argparse
import subprocess
import sys
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons golden", description="check or regenerate the golden master")
    ap.add_argument("--update", action="store_true", help="regenerate the fixtures (needs --approved)")
    ap.add_argument("--approved", metavar="WHY", help="the approved behaviour change the new fixtures record")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    if not (Path.cwd() / "tests" / "golden" / "harness.py").exists():
        sys.exit("run this from the repository root (tests/golden is where the fixtures live)")
    if not a.update:
        sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", "-m", "golden"]))
    if not a.approved:
        sys.exit("regenerating the fixtures changes what counts as correct: say why with --approved \"...\"")
    print(f"regenerating the golden master: {a.approved}")
    sys.exit(subprocess.call([sys.executable, "-m", "tests.golden.update"]))


if __name__ == "__main__":
    main()
