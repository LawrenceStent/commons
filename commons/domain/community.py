"""A community: a charter, a few members, a purse, and a way of deciding things."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from commons.protocol import Identity


class Agent(Protocol):
    """What plays a co-op (commons/agents): it sees an observation and acts through the actions API."""
    name: str

    def turn(self, obs: Any, act: Any) -> None: ...


@dataclass
class Community:
    name: str
    members: int
    capabilities: frozenset[str]
    strategy: Agent
    charter: str = ""
    identity: Identity = field(init=False)
    workspace: Any = None  # a commons.substrate.workspace.Workspace, for a co-op that keeps files
    active: bool = True
    thinking: int = 0  # members funded this cycle
    capacity: int = 0  # actions (bids, prime jobs) left this cycle
    deliveries: dict[str, int] = field(default_factory=dict)  # successful deliveries per capability
    parent: str | None = None  # the community this one forked from
    dissolved: bool = False  # merged into another; kept so its history and signatures still resolve
    doctrine: str = ""  # how it works (a method, a strategy, a beat), beside its charter (what it's for)

    def __post_init__(self):
        self.identity = Identity(self.name)
        self.capabilities = frozenset(self.capabilities)

    def can(self, capability: str) -> bool:
        return capability in self.capabilities
