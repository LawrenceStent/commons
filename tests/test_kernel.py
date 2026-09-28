"""K1: the kernel knows how any society works and nothing about what one is for.

Everything specific to a domain lives in a pack under packs/. This test keeps it that way: it fails if a
domain word from the earn-online pack creeps back into the kernel.
"""

import re
from pathlib import Path

from sim.engine import Params, World
from sim.pack import TemplateWorkSource, load

ROOT = Path(__file__).parent.parent
KERNEL = ["sim", "society", "runtime", "substrate", "protocol", "console"]
DOMAIN = re.compile(r'"(research|build|design|write)"|product|bike|espresso|buyer|marketplace|launch kit|'
                    r'coop-[abc]|"studio"|"lab"|tagline', re.IGNORECASE)


def test_no_domain_words_in_the_kernel():
    hits = []
    for pkg in KERNEL:
        for path in (ROOT / pkg).rglob("*.py"):
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if DOMAIN.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert not hits, "domain words in the kernel (move them into a pack):\n" + "\n".join(hits)


def test_a_world_runs_on_any_pack():
    """A toy pack, defined here in a few lines, runs on the unchanged kernel."""
    from dataclasses import replace

    from society.community import Community
    from society.strategies import Cooperator

    toy = replace(
        load(),
        name="toy",
        brief="WHAT THIS SOCIETY IS FOR\nTidying gardens.",
        capabilities=("dig", "plant"),
        work_source=TemplateWorkSource(["a rose bed", "a herb patch"],
                                       {"dig": ("Dig {subject}.", "Dug evenly."), "plant": ("Plant {subject}.", "Planted.")},
                                       title="Tidy {subject}"),
        population=lambda: [Community("diggers", 3, {"dig"}, Cooperator()), Community("planters", 3, {"plant"}, Cooperator())],
    )
    w = World(Params(seed=0, verify=False), pack=toy).run(60)
    w.ledger.check()
    assert w.jobs_done > 0 and all(j.title.startswith("Tidy ") for j in w.jobs.values())
    assert w.known_capabilities == {"dig", "plant"}


def test_packs_load_by_name_and_unknown_ones_are_refused():
    import pytest

    assert load("earn_online").name == "earn_online"
    with pytest.raises(ValueError, match="no pack called"):
        load("nonexistent")
