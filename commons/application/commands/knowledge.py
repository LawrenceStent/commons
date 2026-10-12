"""Knowledge: playbooks in the library, the archive, and the web behind the gate."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from commons.application.commands.base import CommandBase
from commons.application.commands.pipeline import command
from commons.application.screening import screen
from commons.application.services.findings import PROPOSE, question_id
from commons.application.observation import Outcome
from commons.domain.ids import PassageId, PlaybookId
from commons.protocol.knowledge import Publish
from commons.substrate.ledger import InsufficientFunds

if TYPE_CHECKING:
    pass

MAX_READ = 5  # passages per read_archive call
WEAK = 0.5  # a search whose best passage shares less than this share of the query's words found nothing useful


class KnowledgeCommands(CommandBase):
    @command()
    def publish(self, capability: str, title: str, text: str) -> Outcome:
        if not self.me.can(capability):
            return Outcome(False, "you can only publish methods for capabilities you have")
        if any(p.author == self.me.name and p.capability == capability for p in self.w.library.values()):
            return Outcome(False, f"you already have a {capability} playbook in the library")
        if (err := self._size_ok(text)) is not None:
            return err
        cost = self.w.params.knowledge.publish_cost
        pid = hashlib.sha256(f"{self.me.name}:{capability}:{text}".encode()).hexdigest()[:10]
        if not self._send(Publish(playbook_id=pid, capability=capability, title=title[:120], content_hash=pid)):
            return Outcome(False, "rate-limited: your standing caps how much you can post per cycle")
        try:
            self.w.meter.charge(self.me.name, cost, cycle=self.w.cycle, memo=f"publish {pid}")
        except InsufficientFunds:
            return Outcome(False, f"publishing costs {cost}; you can't afford it")
        self.w.add_playbook(pid, self.me.name, capability, title[:120], text)
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
            return Outcome(True, f"nothing in the archive matches {query!r}. If you need it, web_search for it, then "
                                 "web_fetch a page: what you read joins the archive.")
        best = max(self.w.archive.coverage(p.id, query) for p, _ in hits)
        lines = [f"{p.id} ({p.source}): {' '.join(p.text.split())[:160]}…" for p, _ in hits]
        if best < WEAK:  # the closest passages share few of the words asked about: almost certainly not what's needed
            return Outcome(True, f"nothing in the archive covers {query!r} well (the closest passage shares {best:.0%} of "
                                 "its words), so it has probably not been read yet: web_search for it, then web_fetch a "
                                 "page. Weak matches, only if one is clearly relevant:\n" + "\n".join(lines[:2]))
        return Outcome(True, "Archive passages (read the ones you need in full with one read_archive call):\n" + "\n".join(lines))

    @command()
    def read_archive(self, passage_ids: PassageId | list[PassageId]) -> Outcome:
        """Free: up to `MAX_READ` archive passages in full, as reference material. Reading several in one call saves a
        round of thinking each (in a live run, stewards read one at a time and every read re-sent the conversation).
        An unknown id is named in the answer; the call fails only if none was found."""
        ids = list(dict.fromkeys([passage_ids] if isinstance(passage_ids, str) else map(str, passage_ids)))[:MAX_READ]
        if len(ids) == 1 and "#" not in ids[0] and (whole := self.w.archive.of_source(ids[0])):
            first = whole[:MAX_READ]  # a source's name: its first passages, and the ids of the rest
            rest = f"\n\n{ids[0]} has {len(whole)} passages; read more by id: {', '.join(x.id for x in whole[MAX_READ:])}" \
                if len(whole) > MAX_READ else ""
            text = "\n\n".join(f"Reference material from {p.source} ({p.id}):\n{p.text}" for p in first)
            return Outcome(True, text + rest, ",".join(p.id for p in first))
        found = [p for pid in ids if (p := self.w.archive.get(pid)) is not None]
        missing = [f"no archive passage {pid}; search_archive gives valid ids" for pid in ids
                   if pid not in {p.id for p in found}]
        if not found:
            return Outcome(False, "; ".join(missing) or "name at least one passage id")
        text = "\n\n".join(f"Reference material from {p.source} ({p.id}):\n{p.text}" for p in found)
        return Outcome(True, "\n\n".join([text, *missing]), ",".join(p.id for p in found))

    @command(lock=False)
    def web_search(self, query: str) -> Outcome:
        """Search the web through the gate. Free in credits; the operator's policy may make it wait for approval."""
        return self.w.web_desk.call(self.me.name, self.actor, "web_search", query)

    @command(lock=False)
    def web_fetch(self, url: str) -> Outcome:
        """Read a page through the gate; it joins the archive, to cite as [archive: <id>]."""
        return self.w.web_desk.call(self.me.name, self.actor, "web_fetch", url)

    @command()
    def propose_question(self, question: str, why: str = "") -> Outcome:
        """A follow-up question from a gap (F4): screened like the society's own questions, then to your gate."""
        findings = self.w.findings
        if findings is None or not self.w.pack.followups:
            return Outcome(False, "this society doesn't take proposed questions")
        question = " ".join(str(question).split())[:400]
        if why_not := screen(self.w, self.me.name, "question", question):
            return Outcome(False, why_not)
        qid = question_id(question)
        subjects = getattr(self.w.pack.work_source, "subjects", ())
        if qid in {question_id(s) for s in subjects} or qid in findings.proposed or findings.load(qid) is not None:
            return Outcome(False, "this society already has that question")
        findings.proposed[qid] = question
        out = self.w.approvals.request(self.me.name, self.actor, PROPOSE, "govern", qid,
                                       f"Follow-up question: {question}\nWhy: {str(why)[:400]}")
        if not out.ok:
            findings.proposed.pop(qid, None)
        return out

