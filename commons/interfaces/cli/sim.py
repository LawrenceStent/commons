"""commons sim [cycles] [--no-rep] [--seed N] [--pack NAME]"""

import argparse
import time

from commons.application.services.recorder import summary
from commons.application.society import Params, World
from commons.domain.pack import load as load_pack


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons sim", description="run a scripted society")
    ap.add_argument("cycles", type=int, nargs="?", default=200, help="how many cycles (default 200)")
    ap.add_argument("--no-rep", action="store_true", help="control run: reputation disabled")
    ap.add_argument("--seed", type=int, default=0, help="random seed")
    ap.add_argument("--no-verify", action="store_true", help="skip signature checks on the bus (faster; experiments only)")
    ap.add_argument("--pack", default=None, help="which society (a folder under packs/; default earn_online)")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    t = time.perf_counter()
    pack = load_pack(a.pack)
    w = World(Params(**{**pack.params, "seed": a.seed, "reputation": not a.no_rep, "verify": not a.no_verify}),
              pack=pack).run(a.cycles)
    w.ledger.check()
    print(summary(w))
    print(f"{a.cycles} cycles in {time.perf_counter() - t:.1f}s")


if __name__ == "__main__":
    main()
