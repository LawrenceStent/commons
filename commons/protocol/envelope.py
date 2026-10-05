"""Signed, content-addressed envelopes: the only thing that travels on the bus."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar, TypeVar

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from pydantic import BaseModel, ConfigDict


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


class Message(BaseModel):
    """Base for every protocol body. Subclasses set `family` and `verb`."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    family: ClassVar[str]
    verb: ClassVar[str]


REGISTRY: dict[tuple[str, str], type[Message]] = {}


M = TypeVar("M", bound="Message")


def message(family: str, verb: str):
    def register(cls: type[M]) -> type[M]:
        cls.family, cls.verb = family, verb
        REGISTRY[(family, verb)] = cls
        return cls

    return register


class Identity:
    """A community's signing key. The id is the name other parties know it by."""

    def __init__(self, id: str, key: Ed25519PrivateKey | None = None):
        self.id = id
        self._key = key or Ed25519PrivateKey.generate()
        self.public = self._key.public_key()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def __getstate__(self) -> dict:  # the key as raw bytes: key objects can't be pickled (a saved society)
        return {"id": self.id, "key": self._key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())}

    def __setstate__(self, state: dict) -> None:
        self.__init__(state["id"], Ed25519PrivateKey.from_private_bytes(state["key"]))


class Envelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    family: str
    verb: str
    sender: str
    cycle: int
    body: dict[str, Any]
    sig: str

    @staticmethod
    def _header(family: str, verb: str, sender: str, cycle: int, body: dict) -> dict:
        return {"family": family, "verb": verb, "sender": sender, "cycle": cycle, "body": body}

    @classmethod
    def seal(cls, identity: Identity, msg: Message, cycle: int) -> Envelope:
        body = msg.model_dump(mode="json")
        raw = canonical(cls._header(msg.family, msg.verb, identity.id, cycle, body))
        return cls(
            id=hashlib.sha256(raw).hexdigest(),
            family=msg.family,
            verb=msg.verb,
            sender=identity.id,
            cycle=cycle,
            body=body,
            sig=identity.sign(raw).hex(),
        )

    def verify(self, public: Ed25519PublicKey) -> bool:
        raw = canonical(self._header(self.family, self.verb, self.sender, self.cycle, self.body))
        if hashlib.sha256(raw).hexdigest() != self.id:
            return False
        try:
            public.verify(bytes.fromhex(self.sig), raw)
        except (InvalidSignature, ValueError):
            return False
        return True

    def open(self) -> Message:
        return REGISTRY[(self.family, self.verb)].model_validate(self.body)
