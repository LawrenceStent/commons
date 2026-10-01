"""The whole coordination language. Importing this package registers every message type."""

from commons.protocol import contract, knowledge, population, reputation  # noqa: F401
from commons.protocol.envelope import REGISTRY, Envelope, Identity, Message

FAMILIES = ("contract", "reputation", "population", "knowledge")

__all__ = ["REGISTRY", "Envelope", "Identity", "Message", "FAMILIES"]
