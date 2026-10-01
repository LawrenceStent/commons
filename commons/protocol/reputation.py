"""Reputation: gossip · attest · dispute."""

from pydantic import Field

from commons.protocol.envelope import Message, message


@message("reputation", "attest")
class Attest(Message):
    """First-hand outcome report. Only valid for a job the sender settled with the subject."""

    job_id: str
    subject: str
    capability: str
    outcome: float = Field(ge=0, le=1)


@message("reputation", "gossip")
class Gossip(Message):
    """Second-hand relay of the sender's direct beliefs; receivers discount it."""

    subject: str
    capability: str
    score: float = Field(ge=0, le=1)
    evidence: float = Field(ge=0)


@message("reputation", "dispute")
class Dispute(Message):
    job_id: str
    subject: str
    reason: str
