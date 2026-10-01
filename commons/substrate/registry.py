"""Capability registry: A2A-style agent cards, and the public keys the bus verifies against."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import BaseModel


class AgentCard(BaseModel):
    """Subset of the A2A agent card: enough for discovery between communities."""

    name: str
    description: str = ""
    skills: list[str]
    public_key: str  # raw Ed25519, hex


class Registry:
    def __init__(self):
        self.cards: dict[str, AgentCard] = {}
        self._keys: dict[str, Ed25519PublicKey] = {}

    def register(self, name: str, public: Ed25519PublicKey, skills: list[str], description: str = "") -> AgentCard:
        raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        card = AgentCard(name=name, description=description, skills=sorted(skills), public_key=raw)
        self.cards[name] = card
        self._keys[name] = public
        return card

    def key(self, name: str) -> Ed25519PublicKey | None:
        return self._keys.get(name)

    def providers(self, skill: str) -> list[str]:
        return sorted(n for n, c in self.cards.items() if skill in c.skills)
