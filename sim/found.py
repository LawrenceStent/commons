"""Found a society from your brief, then approve it.

    uv run python -m sim.found NAME --pack earn_online --brief brief.md [--questions FILE] [--context DIR] [--coops 4] \
        --backend lmstudio --model <id>        # drafts societies/NAME/ (one model call)
    uv run python -m sim.found NAME --approve  # checks the blueprints you've read and edited, and approves them
    uv run python -m sim.live --society NAME   # runs it

--backend fake drafts deterministic placeholder co-ops (for trying the flow without a model).
"""

import argparse
import sys
from pathlib import Path

from runtime.backends import BackendChoiceError, FakeBackend, add_backend_args, choose_backend
from sim import founding
from sim.pack import load as load_pack

ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--approve", action="store_true")
ap.add_argument("--pack", default=None)
ap.add_argument("--brief", help="a text or markdown file: what this society is for, in your words")
ap.add_argument("--questions", help="a file of subjects the society will work on, one per line (else the pack's defaults)")
ap.add_argument("--context", help="a folder of reference files: summarised for drafting, then kept as the archive")
ap.add_argument("--coops", type=int, default=4)
ap.add_argument("--seed", type=int, default=0)
add_backend_args(ap, "drafting model (LM Studio: the loaded model's id; default claude-sonnet-5 on anthropic)")
ap.add_argument("--max-tokens", type=int, default=4000, help="raise for models that reason first (e.g. 12000)")
a = ap.parse_args()


def show(errors, warnings):
    for e in errors:
        print(f"  ✗ {e}")
    for w in warnings:
        print(f"  ! {w}")


if a.approve:
    try:
        errors, warnings = founding.approve(a.name)
    except founding.FoundingError as e:
        sys.exit(str(e))
    show(errors, warnings)
    sys.exit(f"not approved: fix {founding.ROOT / a.name / 'blueprints.toml'} first" if errors
             else print(f"approved. Run it:  uv run python -m sim.live --society {a.name} --backend lmstudio --model <id>"))

if not a.brief:
    sys.exit("--brief FILE is required to found a society")
pack = load_pack(a.pack)
caps = list(pack.capabilities)


def placeholder(system, prompt, schema):
    """--backend fake: deterministic placeholder co-ops, two skills each, for trying the flow without a model."""
    pairs = [caps[i:i + 2] for i in range(0, len(caps), 2)] or [caps]
    return {"coops": [{"name": f"coop-{i + 1}", "members": 3, "capabilities": pairs[i % len(pairs)],
                       "charter": f"placeholder co-op {i + 1} (drafted without a model)",
                       "doctrine": "placeholder: edit before approving"} for i in range(a.coops)]}


try:
    backend, model = choose_backend(a.backend, a.model, a.yes_spend, default_model="claude-sonnet-5",
                                    fake=lambda: FakeBackend(respond=placeholder), cost="one call")
except BackendChoiceError as e:
    sys.exit(str(e))

try:
    folder, errors, warnings = founding.found(a.name, a.pack, Path(a.brief).read_text(), Path(a.context) if a.context else None,
                                              a.coops, backend, model, seed=a.seed, max_tokens=a.max_tokens,
                                              questions=Path(a.questions).read_text() if a.questions else "")
except founding.FoundingError as e:
    sys.exit(str(e))
blueprints, _ = founding.read_blueprints(folder / "blueprints.toml")
print(f"drafted {len(blueprints)} co-ops in {folder}/blueprints.toml:")
for b in blueprints:
    print(f"  {b.name} ({', '.join(b.capabilities)}, {b.members} members): {b.charter}\n      doctrine: {b.doctrine}")
show(errors, warnings)
print(f"\nRead and edit {folder}/blueprints.toml, then:  uv run python -m sim.found {a.name} --approve")
