"""The dependency rule (docs/REFACTOR-PLAN.md §1.1), checked from the source.

Each layer imports only the layers inside it:

    protocol < domain < substrate < application < agents < adapters < interfaces < packs

Type-only imports (under `if TYPE_CHECKING`) count: a type is a dependency too. Known exceptions are listed with the
stage that removes them. The lists may only shrink: an exception that no longer occurs fails the test, so it gets
deleted when it's fixed.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
RANK = {"protocol": 0, "domain": 1, "substrate": 2, "application": 3, "agents": 4, "adapters": 5, "interfaces": 6,
        "packs": 7}

# (file, imported module): why it's allowed for now
OUTWARD: dict[tuple[str, str], str] = {}


def layer_of(module_or_path: str) -> str | None:
    parts = module_or_path.replace("/", ".").split(".")
    if parts[0] == "packs":
        return "packs"
    if parts[0] == "commons" and len(parts) > 1 and parts[1] in RANK:
        return parts[1]
    return None


def _imports():
    for path in sorted((ROOT / "commons").rglob("*.py")) + sorted((ROOT / "packs").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        src = layer_of(rel)
        tree = ast.parse(path.read_text())
        nested = {id(n) for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                  for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))}
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for m in mods:
                if (dst := layer_of(m)) is not None:
                    yield rel, src, m, dst, id(node) in nested


def test_no_import_points_outward():
    found = {(rel, m) for rel, src, m, dst, _ in _imports() if src and RANK[dst] > RANK[src]}
    assert not found - OUTWARD.keys(), f"new outward imports (fix, don't list): {sorted(found - OUTWARD.keys())}"
    assert not OUTWARD.keys() - found, f"fixed, so delete from OUTWARD: {sorted(OUTWARD.keys() - found)}"


def test_no_hidden_imports():
    """Imports of our own modules inside functions hide dependencies (A2)."""
    assert not sorted((rel, m) for rel, _, m, _, nested in _imports() if nested)


def test_the_domain_imports_only_the_protocol_and_itself():
    bad = sorted((rel, m) for rel, src, m, dst, _ in _imports() if src == "domain" and dst not in ("protocol", "domain"))
    assert not bad, bad
