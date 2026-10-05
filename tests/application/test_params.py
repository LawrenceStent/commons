"""R9: settings in groups. Every setting is in exactly one group; code reads them by group, and each module reads only
the groups declared for it below (a new need is a deliberate edit here, not an accident)."""

import dataclasses
import re

import pytest

from commons.application.params import GROUPS, Params
from tests.paths import ROOT

COMMONS = ROOT / "commons"
READS = {
    "application/commands/knowledge.py": {"knowledge"},
    "application/commands/market.py": {"contracts", "market"},
    "application/commands/planning.py": {"ventures"},
    "application/cycle.py": {"runtime", "trust"},
    "application/observe.py": {"contracts", "knowledge", "market", "money", "population", "ventures"},
    "application/population.py": {"population", "run", "storage"},
    "application/services/board.py": {"market", "run", "storage"},
    "application/services/contract_net.py": {"contracts", "market", "storage"},
    "application/services/gossip.py": {"trust"},
    "application/services/grading.py": {"market", "runtime"},
    "application/services/payments.py": {"money"},
    "application/services/upkeep.py": {"money"},
    "application/services/ventures.py": {"market", "ventures"},
    "application/society.py": {"contracts", "market", "money", "run", "storage", "trust"},
    "application/ventures.py": {"contracts"},
    "application/queries.py": {"market", "money", "population", "run"},
}


def test_every_setting_is_in_exactly_one_group():
    names = [n for g in GROUPS.values() for n in g]
    assert len(names) == len(set(names))
    assert set(names) == {f.name for f in dataclasses.fields(Params) if f.init}  # the settings, not the groups


def test_groups_mirror_the_flat_settings_and_nothing_changes_after():
    p = Params(seed=3, job_ttl=12, economy="grant")
    assert (p.run.seed, p.market.job_ttl, p.money.economy) == (3, 12, "grant")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.job_ttl = 5


def test_modules_read_only_their_groups_and_never_flat_names():
    flat = "|".join(sorted((n for g in GROUPS.values() for n in g), key=len, reverse=True))
    groups = "|".join(GROUPS)
    for path in COMMONS.rglob("*.py"):
        rel = path.relative_to(COMMONS).as_posix()
        if rel == "application/params.py":
            continue
        text = path.read_text()
        read = set(re.findall(rf"(?:params|\bp)\.({groups})\.", text))
        assert read <= READS.get(rel, set()), f"{rel} reads {sorted(read - READS.get(rel, set()))}"
        assert not re.search(rf"\.params\.({flat})\b", text), f"{rel} reads a setting by its flat name"


def test_every_setting_is_in_exactly_one_group_with_the_same_type():
    from dataclasses import fields

    from commons.application.params import CONFIGS, Params

    flat = {f.name: f.type for f in fields(Params) if f.init}
    grouped = [(f.name, f.type) for c in CONFIGS.values() for f in fields(c)]
    assert sorted(n for n, _ in grouped) == sorted(flat)  # all of them, once each
    assert all(flat[n] == t for n, t in grouped)
