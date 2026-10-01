"""The dependency rule (docs/REFACTOR-PLAN.md §1.1), checked from the source.

Inner layers never import outer ones. Until the R3 move, today's packages are ranked inner to outer; every import that
points outward is listed below as a known exception with the audit finding it belongs to. The lists may only shrink:
an exception that no longer occurs fails the test too, so it gets deleted when it's fixed.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
RANK = {"protocol": 0, "substrate": 1, "society": 2, "sim": 3, "runtime": 4, "console": 5, "packs": 6}

# (file, imported module): why it's allowed for now
OUTWARD = {
    ("sim/calibrate.py", "runtime.backends"): "A5: R3 moves CLIs to interfaces",
    ("sim/found.py", "runtime.backends"): "A5: R3",
    ("sim/live.py", "runtime.backends"): "A5: R3",
    ("sim/live.py", "runtime.fakes"): "A5: R3",
    ("sim/live.py", "runtime.steward"): "A5: R3",
    ("sim/live.py", "runtime.web"): "A5: R3",
    ("sim/live.py", "console.app"): "A5: R3",
}

# imports of our own modules inside functions (A2): each one hides a dependency
IN_FUNCTIONS = {
    ("sim/calibration.py", "sim.grader"), ("sim/calibration.py", "sim.ventures"), ("sim/engine.py", "sim.scorecard"),
    ("sim/engine.py", "sim.market"), ("sim/founding.py", "society.community"),
    ("sim/founding.py", "society.strategies"), 
}


def _imports():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        top = rel.split("/")[0]
        if top not in RANK:
            continue
        tree = ast.parse(path.read_text())
        nested = {id(n) for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                  for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))}
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for m in mods:
                if m.split(".")[0] in RANK:
                    yield rel, top, m, id(node) in nested


def test_no_import_points_outward():
    found = {(rel, m) for rel, top, m, _ in _imports() if RANK[m.split(".")[0]] > RANK[top]}
    assert not found - OUTWARD.keys(), f"new outward imports (fix, don't list): {sorted(found - OUTWARD.keys())}"
    assert not OUTWARD.keys() - found, f"fixed, so delete from OUTWARD: {sorted(OUTWARD.keys() - found)}"


def test_no_hidden_imports():
    found = {(rel, m) for rel, top, m, nested in _imports() if nested}
    assert not found - IN_FUNCTIONS, f"new imports inside functions (fix, don't list): {sorted(found - IN_FUNCTIONS)}"
    assert not IN_FUNCTIONS - found, f"fixed, so delete from IN_FUNCTIONS: {sorted(IN_FUNCTIONS - found)}"
