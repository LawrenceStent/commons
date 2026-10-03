"""Regenerate the golden-master fixtures. Only after a behaviour change you have approved: the point of the
fixtures is that refactoring never needs this. With no names, it also rewrites the dashboard JSON fixtures
(tests/interfaces/test_dashboard.py)."""

import gzip
import json
import sys

from tests.golden.harness import RUNS, capture, digest, save
from tests.interfaces import test_dashboard as dashboard

names = sys.argv[1:] or list(RUNS)
for name in names:
    streams = capture(name)
    save(name, streams)
    print(f"{name}: " + " ".join(f"{k} {len(v)}" for k, v in streams.items()), digest(streams))
if not sys.argv[1:]:  # the dashboard's JSON is pinned with the runs, so a full update covers it too
    for pack_name in dashboard.CASES:
        with gzip.open(dashboard.path(pack_name), "wt") as f:
            json.dump(dashboard.capture(pack_name), f)
        print("wrote", dashboard.path(pack_name).name)
