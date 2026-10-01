"""Knowledge: playbooks in the library, the archive, and the web behind the gate."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from commons.application.commands.base import MAX_ARTIFACT, CommandBase
from commons.application.commands.pipeline import command
from commons.application.observation import Outcome
from commons.domain.ids import PassageId, PlaybookId
from commons.protocol.knowledge import Publish
from commons.substrate.ledger import InsufficientFunds

if TYPE_CHECKING:
    pass


class KnowledgeCommands(CommandBase):
    @command()
    def publish(self, capability: str, title: str, text: str) -> Outcome:
        if not self.me.can(capability):
            return Outcome(False, "you can only publish methods for capabilities you have")
        if any(p.author == self.me.name and p.capability == capability for p in self.w.library.values()):
            return Outcome(False, f"you already have a {capability} playbook in the library")
        cost = self.w.params.knowledge.publish_cost
        pid = hashlib.sha256(f"{self.me.name}:{capability}:{text}".encode()).hexdigest()[:10]
        if not self._send(Publish(playbook_id=pid, capability=capability, title=title[:120], content_hash=pid)):
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        try:
            self.w.meter.charge(self.me.name, cost, cycle=self.w.cycle, memo=f"publish {pid}")
        except InsufficientFunds:
            return Outcome(False, f"publishing costs {cost}; you can't afford it")
        self.w.add_playbook(pid, self.me.name, capability, title[:120], text[:MAX_ARTIFACT])
        return Outcome(True, f"published playbook {pid}; you earn royalties whenever it is cited", pid)

    @command()
    def read_playbook(self, playbook_id: PlaybookId) -> Outcome:
        pb = self.w.library.get(playbook_id)
        if pb is None:
            return Outcome(False, f"no playbook {playbook_id}")
        return Outcome(True, pb.text, pb.id)

    @command()
    def search_archive(self, query: str) -> Outcome:
        """Free: keyword search over the society's reference archive. Returns passage ids and short snippets."""
        if not len(self.w.archive):
            return Outcome(False, "this society has no archive")
        hits = self.w.archive.search(str(query))
        if not hits:
            return Outcome(True, f"nothing in the archive matches {query!r}")
        lines = [f"{p.id} ({p.source}): {' '.join(p.text.split())[:160]}…" for p, _ in hits]
        return Outcome(True, "Archive passages (read one in full with read_archive):\n" + "\n".join(lines))

    @command()
    def read_archive(self, passage_id: PassageId) -> Outcome:
        """Free: one archive passage in full, as reference material."""
        p = self.w.archive.get(str(passage_id))
        if p is None:
            return Outcome(False, f"no archive passage {passage_id}; search_archive gives valid ids")
        return Outcome(True, f"Reference material from {p.source} ({p.id}):\n{p.text}", p.id)

    @command(lock=False)
    def web_search(self, query: str) -> Outcome:
        """Search the web through the gate. Free in credits; the operator's policy may make it wait for approval."""
        return self.w.web_desk.call(self.me.name, self.actor, "web_search", query)

    @command(lock=False)
    def web_fetch(self, url: str) -> Outcome:
        """Read a page through the gate; it joins the archive, to cite as [archive: <id>]."""
        return self.w.web_desk.call(self.me.name, self.actor, "web_fetch", url)
