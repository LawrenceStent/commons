"""python -m sim [cycles] [--no-rep] [--seed N]"""

import argparse
import time

from sim.engine import Params, World, summary

ap = argparse.ArgumentParser()
ap.add_argument("cycles", type=int, nargs="?", default=200)
ap.add_argument("--no-rep", action="store_true", help="control run: reputation disabled")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--no-verify", action="store_true")
a = ap.parse_args()

t = time.perf_counter()
w = World(Params(seed=a.seed, reputation=not a.no_rep, verify=not a.no_verify)).run(a.cycles)
w.ledger.check()
print(summary(w))
print(f"{a.cycles} cycles in {time.perf_counter() - t:.1f}s")
