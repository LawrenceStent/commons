"""Knowledge: publish · cite. (Royalties are paid by the ledger, in-process.)"""

from commons.protocol.envelope import Message, message


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
