"""Architecture metrics: the measurements behind docs/ARCHITECTURE-AUDIT.md, re-run after every refactor stage.

    uv run python -m tools.arch_metrics

Everything is read from the source (ast and regular expressions); nothing is imported or run.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKIP = {"tests", "tools", ".venv", "runs", "societies", "operator", "docs"}


def _sources():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in SKIP or rel.parts[0].startswith("."):
            continue
        yield rel, path.read_text()


def _ours(module: str, packages: set[str]) -> str | None:
    top = module.split(".")[0]
    return top if top in packages else None


def _cycles(edges: dict[str, set[str]]) -> list[tuple[str, str]]:
    return sorted((a, b) for a in edges for b in edges[a] if a < b and a in edges.get(b, set()))


def measure() -> dict[str, object]:
    files = list(_sources())
    packages = {rel.parts[0] for rel, _ in files if len(rel.parts) > 1}
    funcs, classes, nested, edges = [], [], 0, defaultdict(set)
    private, status, economy = 0, 0, 0
    for rel, text in files:
        tree = ast.parse(text)
        top = rel.parts[0]
        inner = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((node.end_lineno - node.lineno + 1, f"{rel}:{node.lineno} {node.name}"))
                inner |= {id(n) for n in ast.walk(node) if isinstance(n, (ast.Import, ast.ImportFrom)) and n is not node}
            elif isinstance(node, ast.ClassDef):
                classes.append((node.end_lineno - node.lineno + 1, f"{rel}:{node.lineno} {node.name}"))
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for m in mods:
                if (dep := _ours(m, packages)) and dep != top:
                    edges[top].add(dep)
                if _ours(m, packages) and id(node) in inner:
                    nested += 1
        # another object's private member: `x._name` where x isn't self/cls (module-private helpers excluded)
        private += len(re.findall(r"\b(?!self\b|cls\b)[a-z_]+\.(?:w\.)?_[a-z][a-z_]*\b(?!\()", text)) + \
                   len(re.findall(r"\bself\.w\._[a-z]", text))
        status += len(re.findall(r"status\s*(?:==|!=|in)\s*\(?\"", text))
        economy += len(re.findall(r"economy\s*(?:==|!=)", text))
    lines = sum(t.count("\n") for _, t in files)
    return {
        "lines (excluding tests)": lines,
        "packages": len(packages),
        "package cycles": _cycles(edges),
        "largest class": max(classes),
        "classes over 300 lines": sum(n > 300 for n, _ in classes),
        "functions over 70 / 40 / 30 lines": (sum(n > 70 for n, _ in funcs), sum(n > 40 for n, _ in funcs),
                                              sum(n > 30 for n, _ in funcs)),
        "longest function": max(funcs),
        "imports inside functions (ours)": nested,
        "status string comparisons": status,
        "economy flag checks": economy,
        "cross-object private access (approx.)": private,
    }


if __name__ == "__main__":
    for k, v in measure().items():
        print(f"{k:<40} {v}")
