"""A pack's outside world (Phase 2): which services have keys, and linking an item you listed by hand.

    uv run commons channels --pack P            which services have keys in .env (names only, never values)
    uv run commons channels --pack P --check    also one free, read-only call to each, to prove the keys work
    uv run commons link NAME ITEM CHANNEL ID    an item listed by hand on a channel, linked so its sales are collected

The services, and what linking means, are the pack's (its `health`, its desk's `link`).
"""

import argparse
import sys

from commons.application import registry
from commons.domain.pack import load as load_pack
from commons.interfaces.cli import live
from commons.interfaces.console.app import open_saved


def main_channels(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="commons channels", description="a pack's outside services and their keys")
    ap.add_argument("--pack", required=True, help="whose services")
    ap.add_argument("--check", action="store_true", help="one free, read-only call to each service that has keys")
    a = ap.parse_args(argv)
    pack = load_pack(a.pack)
    if pack.health is None:
        sys.exit(f"the {pack.name} pack uses no outside services")
    print("\n".join(pack.health(a.check)))


def main_link(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="commons link", description="link an item you listed by hand")
    ap.add_argument("name", help="the society")
    ap.add_argument("item", help="its id in the society's desk (P1, ...)")
    ap.add_argument("channel", help="the channel you listed it on")
    ap.add_argument("listing", help="its id on that channel")
    a = ap.parse_args(argv)
    save = registry.folder_of(a.name) / registry.STATE / "society.save"
    if not save.exists():
        sys.exit(f"no saved society called {a.name} (commons list shows them)")
    live._lock()
    world = open_saved(save)
    link = getattr(world.desk, "link", None)
    if link is None:
        sys.exit(f"{a.name}'s pack has nothing to link")
    try:
        print(link(a.item, a.channel, a.listing))
    except ValueError as e:
        sys.exit(str(e))
    world.save(save)
