"""Found a society from your brief, then approve it.

    uv run commons found NAME --pack earn_online --brief brief.md [--questions FILE] [--context DIR] [--coops 4] \
        --backend lmstudio --model <id>        # drafts societies/NAME/ (one model call)
    uv run commons found NAME --approve  # checks the blueprints you've read and edited, and approves them
    uv run commons run --society NAME   # runs it

--backend fake drafts deterministic placeholder co-ops (for trying the flow without a model).
"""

import argparse
import sys
from pathlib import Path

from commons.adapters.models import BackendChoiceError, FakeBackend, add_backend_args, choose_backend
from commons.application import founding
from commons.domain.pack import load as load_pack


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons found", description="found a society from your brief, then approve it")
    ap.add_argument("name", help="the society: 2-24 lowercase letters, digits or hyphens")
    ap.add_argument("--approve", action="store_true", help="check the (edited) blueprints and approve them")
    ap.add_argument("--pack", default=None, help="which pack it runs on (default earn_online)")
    ap.add_argument("--brief", help="a text or markdown file: what this society is for, in your words")
    ap.add_argument("--questions", help="a file of subjects the society will work on, one per line (else the pack's defaults)")
    ap.add_argument("--context", help="a folder of reference files: summarised for drafting, then kept as the archive")
    ap.add_argument("--coops", type=int, default=4, help="how many co-ops to draft")
    ap.add_argument("--seed", type=int, default=0, help="the society's seed")
    add_backend_args(ap, "drafting model (LM Studio: the loaded model's id; default claude-sonnet-5 on anthropic)")
    ap.add_argument("--max-tokens", type=int, default=4000, help="raise for models that reason first (e.g. 12000)")
    return ap


def show(errors, warnings) -> None:
    for e in errors:
        print(f"  ✗ {e}")
    for w in warnings:
        print(f"  ! {w}")


def approve(name: str) -> None:
    try:
        errors, warnings = founding.approve(name)
    except founding.FoundingError as e:
        sys.exit(str(e))
    show(errors, warnings)
    if errors:
        sys.exit(f"not approved: fix {founding.ROOT / name / 'blueprints.toml'} first")
    print(f"approved. Run it:  uv run commons run --society {name} --backend lmstudio --model <id>")


def placeholder_drafter(capabilities, n: int):
    """--backend fake: deterministic placeholder co-ops, two skills each, for trying the flow without a model."""
    caps = list(capabilities)

    def respond(system, prompt, schema):
        pairs = [caps[i:i + 2] for i in range(0, len(caps), 2)] or [caps]
        return {"coops": [{"name": f"coop-{i + 1}", "members": 3, "capabilities": pairs[i % len(pairs)],
                           "charter": f"placeholder co-op {i + 1} (drafted without a model)",
                           "doctrine": "placeholder: edit before approving"} for i in range(n)]}
    return respond


def found(a) -> None:
    if not a.brief:
        sys.exit("--brief FILE is required to found a society")
    pack = load_pack(a.pack)
    try:
        backend, model = choose_backend(a.backend, a.model, a.yes_spend, default_model="claude-sonnet-5",
                                        fake=lambda: FakeBackend(respond=placeholder_drafter(pack.capabilities, a.coops)),
                                        cost="one call")
        folder, errors, warnings = founding.found(
            a.name, a.pack, Path(a.brief).read_text(), Path(a.context) if a.context else None, a.coops, backend, model,
            seed=a.seed, max_tokens=a.max_tokens, questions=Path(a.questions).read_text() if a.questions else "")
    except (BackendChoiceError, founding.FoundingError) as e:
        sys.exit(str(e))
    blueprints, _ = founding.read_blueprints(folder / "blueprints.toml")
    print(f"drafted {len(blueprints)} co-ops in {folder}/blueprints.toml:")
    for b in blueprints:
        print(f"  {b.name} ({', '.join(b.capabilities)}, {b.members} members): {b.charter}\n      doctrine: {b.doctrine}")
    show(errors, warnings)
    print(f"\nRead and edit {folder}/blueprints.toml, then:  uv run commons found {a.name} --approve")


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    if a.approve:
        approve(a.name)
    else:
        found(a)


if __name__ == "__main__":
    main()
