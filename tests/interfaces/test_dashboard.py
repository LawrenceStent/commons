"""R11.4: the dashboard's JSON (its snapshot, and a co-op's drill-down) is pinned like the golden master: refactoring
the console may not change one field. Regenerate only after an approved change:

    uv run python -m tests.interfaces.test_dashboard
"""

import gzip
import json
from pathlib import Path

import pytest

from commons.application.society import Params, World
from commons.domain.pack import load
from commons.interfaces.console.app import community_detail, snapshot
from tests.golden.harness import _clean
from tests.paths import ROOT

FIXTURES = ROOT / "tests" / "golden" / "fixtures"
CASES = {"earn_online": "coop-a", "tech_for_good": "scouts", "trading": "holder", "osint": "sources"}


def capture(pack_name: str) -> dict:
    pack = load(pack_name)
    w = World(Params(**{**pack.params, "seed": 0}), pack=pack).run(30)
    state = {"world": w, "running": False, "speed": 4.0, "reason": None, "rss_limit": 2 * 1024**3, "stop_at": None}
    return json.loads(json.dumps(_clean({"snapshot": snapshot(state),
                                         "detail": community_detail(w, CASES[pack_name])}), default=str))


def path(pack_name: str) -> Path:
    return FIXTURES / f"dashboard-{pack_name}.json.gz"


@pytest.mark.golden
@pytest.mark.parametrize("pack_name", sorted(CASES))
def test_the_dashboard_json_is_unchanged(pack_name):
    with gzip.open(path(pack_name), "rt") as f:
        expected = json.load(f)
    actual = capture(pack_name)
    for key in expected["snapshot"]:
        assert expected["snapshot"][key] == actual["snapshot"][key], f"snapshot[{key!r}] changed"
    assert expected == actual


if __name__ == "__main__":
    for name in CASES:
        with gzip.open(path(name), "wt") as f:
            json.dump(capture(name), f)
        print("wrote", path(name))
