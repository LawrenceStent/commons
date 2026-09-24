"""Knowledge: publish · cite · royalty."""

from protocol.envelope import Message, message


@message("knowledge", "publish")
class Publish(Message):
    playbook_id: str
    capability: str
    title: str
    content_hash: str


@message("knowledge", "cite")
class Cite(Message):
    playbook_id: str
    job_id: str


@message("knowledge", "royalty")
class Royalty(Message):
    playbook_id: str
    job_id: str
    amount: int
