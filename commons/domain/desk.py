"""Desks: what a pack adds to the kernel when its work isn't jobs and parts (accounts it keeps for each co-op, say).

A desk has its own tools, a section of every co-op's observation, two phases in every cycle (one when it opens, after
the start, one when it closes, before the records), and state that is saved with the society. Its tools run through
the same command pipeline as the kernel's (the lock, the activity log, your operator's limits), and appear in the
steward's tool list only in societies whose pack has a desk. The kernel knows only "a desk".
"""

from __future__ import annotations

from typing import Any, Protocol

World = Any  # the society (application/society.py); typed loosely so the domain doesn't depend on the application


class Desk(Protocol):
    tools: tuple[dict[str, Any], ...]  # name, description, input_schema; fixed (they sit in the cached prompt)

    def call(self, world: World, coop: str, tool: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Do what `coop` asked: (done, what to tell it). Refusals are readable sentences, never exceptions."""
        ...

    def view(self, world: World, coop: str) -> str:
        """What `coop` sees of the desk this turn (empty: nothing)."""
        ...

    def open(self, world: World) -> None:
        """The start of a cycle, under the lock."""
        ...

    def close(self, world: World) -> None:
        """The end of a cycle, under the lock."""
        ...
