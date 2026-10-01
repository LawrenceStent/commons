"""Blueprints: a co-op's constitution, and the rules a society's blueprints must pass. See application/founding.py."""

from __future__ import annotations

import re
from dataclasses import dataclass

from commons.domain.pack import Pack

NAME = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
KINDS = ("llm", "cooperator", "defector", "free-rider")


class FoundingError(ValueError):
    pass


@dataclass(frozen=True)
class Blueprint:
    name: str
    kind: str
    members: int
    capabilities: tuple[str, ...]
    charter: str
    doctrine: str = ""


# ── checking ───────────────────────────────────────────────────
def check(blueprints: list[Blueprint], pack: Pack) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors block approval; warnings are worth reading."""
    errors, warnings = [], []
    if not 2 <= len(blueprints) <= 12:
        errors.append(f"a society starts with 2 to 12 co-ops, not {len(blueprints)}")
    names = [b.name for b in blueprints]
    for dup in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"two co-ops are called {dup}")
    for b in blueprints:
        where = f"co-op {b.name!r}"
        if not NAME.match(b.name):
            errors.append(f"{where}: a name is 2-24 lowercase letters, digits or hyphens, starting with a letter")
        if b.kind not in KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if not 1 <= b.members <= 7:
            errors.append(f"{where}: 1 to 7 members")
        unknown = set(b.capabilities) - set(pack.capabilities)
        if not b.capabilities or unknown:
            errors.append(f"{where}: capabilities must be some of {', '.join(pack.capabilities)}"
                          + (f" (unknown: {', '.join(sorted(unknown))})" if unknown else ""))
        if b.kind == "llm" and not b.charter:
            errors.append(f"{where}: an LLM co-op needs a charter")
        if b.kind == "llm" and set(b.capabilities) == set(pack.capabilities) and len(blueprints) > 1:
            warnings.append(f"{where} has every skill: co-ops that need each other trade more")
    covered = set().union(*(b.capabilities for b in blueprints)) if blueprints else set()
    if missing := set(pack.capabilities) - covered:
        warnings.append(f"no co-op can do {', '.join(sorted(missing))}; every job needing it will be bought from no one")
    return errors, warnings

