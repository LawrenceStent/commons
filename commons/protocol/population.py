"""Population: spawn · retire · fork · merge. Schemas only until Phase 1."""

from commons.protocol.envelope import Message, message


@message("population", "spawn")
class Spawn(Message):
    agent: str
    role: str
    seconded_by: str


@message("population", "retire")
class Retire(Message):
    agent: str


@message("population", "fork")
class Fork(Message):
    new_community: str
    members: list[str]


@message("population", "merge")
class Merge(Message):
    target: str
