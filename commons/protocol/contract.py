"""Contract-net: announce · bid · award · deliver. (Settlement is the ledger's, in-process.)

The only way to get help. There is no escalation path.
Amounts are integer micro-dollars throughout.
"""

from typing import Any

from pydantic import Field

from commons.protocol.envelope import Message, message


@message("contract", "announce")
class Announce(Message):
    job_id: str
    capability: str
    reward: int = Field(gt=0)
    advance_frac: float = Field(ge=0, le=1)
    spec: str = ""


@message("contract", "bid")
class Bid(Message):
    job_id: str
    price: int = Field(gt=0)


@message("contract", "award")
class Award(Message):
    job_id: str
    winner: str
    price: int
    advance: int


@message("contract", "deliver")
class Deliver(Message):
    job_id: str
    artifact: dict[str, Any]
    cites: list[str] = []
