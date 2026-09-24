"""The whole coordination language. Importing this package registers every message type."""

from protocol import contract, gate, governance, knowledge, population, reputation  # noqa: F401
from protocol.envelope import REGISTRY, Envelope, Identity, Message

FAMILIES = ("contract", "governance", "reputation", "population", "knowledge", "gate")

__all__ = ["REGISTRY", "Envelope", "Identity", "Message", "FAMILIES"]
