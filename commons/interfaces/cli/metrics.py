"""Architecture metrics: the measurements behind docs/ARCHITECTURE-AUDIT.md, re-run after every refactor stage.

    uv run commons metrics

Everything is read from the source (ast and regular expressions); nothing is imported or run.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path.cwd()  # the repository it runs in
SKIP = {"tests", ".venv", "runs", "societies", "operator", "docs", "sim"}  # sim/: shims only


def _sources():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in SKIP or rel.parts[0].startswith("."):
            continue
        yield rel, path.read_text()


def _package(parts) -> str:
    """The unit the metrics count: a layer of commons/ (commons.domain, …), or a top-level package (packs)."""
    parts = list(parts)
    return ".".join(parts[:2]) if parts[0] == "commons" and len(parts) > 2 else parts[0]


def _ours(module: str, packages: set[str]) -> str | None:
    name = _package(module.split(".") + ["x"]) if module.startswith("commons.") else module.split(".")[0]
    return name if name in packages else None


def _cycles(edges: dict[str, set[str]]) -> list[tuple[str, str]]:
    return sorted((a, b) for a in edges for b in edges[a] if a < b and a in edges.get(b, set()))


def _scan(files, packages):
    """Per-file measurements: function and class sizes, package edges, hidden imports, and three code smells."""
    funcs, classes, edges = [], [], defaultdict(set)
    counts = dict(nested=0, private=0, status=0, economy=0)
    for rel, text in files:
        tree = ast.parse(text)
        top = _package(rel.parts)
        inner = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(((node.end_lineno or node.lineno) - node.lineno + 1, f"{rel}:{node.lineno} {node.name}"))
                inner |= {id(n) for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom)) and n is not node}
            elif isinstance(node, ast.ClassDef):
                classes.append(((node.end_lineno or node.lineno) - node.lineno + 1, f"{rel}:{node.lineno} {node.name}"))
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for m in mods:
                if (dep := _ours(m, packages)) and dep != top:
                    edges[top].add(dep)
                if _ours(m, packages) and id(node) in inner:
                    counts["nested"] += 1
        # another object's private member: `x._name` where x isn't self/cls (module-private helpers excluded)
        counts["private"] += len(re.findall(r"\b(?!self\b|cls\b)[a-z_]+\.(?:w\.)?_[a-z][a-z_]*\b(?!\()", text)) + \
            len(re.findall(r"\bself\.w\._[a-z]", text))
        counts["status"] += len(re.findall(r"status\s*(?:==|!=|in)\s*\(?\"", text))
        counts["economy"] += len(re.findall(r"economy\s*(?:==|!=)", text))
    return funcs, classes, edges, counts


def measure() -> dict[str, object]:
    files = list(_sources())
    packages = {_package(rel.parts) for rel, _ in files if len(rel.parts) > 1}
    funcs, classes, edges, counts = _scan(files, packages)
    return {
        "lines (excluding tests)": sum(t.count("\n") for _, t in files),
        "packages": len(packages),
        "package cycles": _cycles(edges),
        "largest class": max(classes),
        "classes over 300 lines": sum(n > 300 for n, _ in classes),
        "functions over 70 / 40 / 30 lines": (sum(n > 70 for n, _ in funcs), sum(n > 40 for n, _ in funcs),
                                              sum(n > 30 for n, _ in funcs)),
        "longest function": max(funcs),
        "imports inside functions (ours)": counts["nested"],
        "status string comparisons": counts["status"],
        "economy flag checks": counts["economy"],
        "cross-object private access (approx.)": counts["private"],
    }


def main(argv: list[str] | None = None) -> None:
    for k, v in measure().items():
        print(f"{k:<40} {v}")


if __name__ == "__main__":
    main()
