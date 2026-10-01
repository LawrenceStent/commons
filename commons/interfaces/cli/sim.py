"""commons sim [cycles] [--no-rep] [--seed N] [--pack NAME]"""

import argparse
import time

from commons.application.world import Params, World, summary
from commons.domain.pack import load as load_pack

ap = argparse.ArgumentParser()
ap.add_argument("cycles", type=int, nargs="?", default=200)
ap.add_argument("--no-rep", action="store_true", help="control run: reputation disabled")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--no-verify", action="store_true")
ap.add_argument("--pack", default=None, help="which society (a folder under packs/; default earn_online)")
a = ap.parse_args()

t = time.perf_counter()
pack = load_pack(a.pack)
w = World(Params(**{**pack.params, "seed": a.seed, "reputation": not a.no_rep, "verify": not a.no_verify}), pack=pack).run(a.cycles)
w.ledger.check()
print(summary(w))
print(f"{a.cycles} cycles in {time.perf_counter() - t:.1f}s")
