"""Regenerate the golden-master fixtures. Only after a behaviour change you have approved: the point of the
fixtures is that refactoring never needs this."""

import sys

from tests.golden.harness import RUNS, capture, digest, save

names = sys.argv[1:] or list(RUNS)
for name in names:
    streams = capture(name)
    save(name, streams)
    print(f"{name}: " + " ".join(f"{k} {len(v)}" for k, v in streams.items()), digest(streams))
