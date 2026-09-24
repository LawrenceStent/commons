"""Gate: request · approve · deny · revoke. Anything touching the outside world stops here."""

from typing import Any

from protocol.envelope import Message, message


@message("gate", "request")
class Request(Message):
    request_id: str
    action: str
    risk_class: str
    venture: str = ""
    detail: dict[str, Any] = {}


@message("gate", "approve")
class Approve(Message):
    request_id: str


@message("gate", "deny")
class Deny(Message):
    request_id: str
    reason: str


@message("gate", "revoke")
class Revoke(Message):
    request_id: str
    reason: str = ""
