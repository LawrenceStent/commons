"""R13: the type checker holds the code to its types. pyright, basic mode, over commons/ and packs/ (configured in
pyproject.toml), must report nothing: a new error fails the suite, as a broken layer rule does."""

import json
import subprocess
import sys
from pathlib import Path

from tests.paths import ROOT


def test_pyright_finds_nothing():
    pyright = Path(sys.executable).parent / "pyright"
    done = subprocess.run([str(pyright), "--outputjson"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    report = json.loads(done.stdout)
    errors = [f"{d['file'].split(str(ROOT) + '/', 1)[-1]}:{d['range']['start']['line'] + 1}: {d['message'].splitlines()[0]}"
              for d in report["generalDiagnostics"] if d["severity"] == "error"]
    assert not errors, "type errors (uv run pyright):\n" + "\n".join(errors[:30])
