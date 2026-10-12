"""What every command shares: the co-op it acts for, signing and sending protocol messages, capacity, citations."""

from __future__ import annotations

import difflib

from typing import TYPE_CHECKING

from commons.application.observation import Outcome
from commons.domain.archive import citations as archive_citations
from commons.application.screening import review_work, screen
from commons.domain.grading import is_tagged
from commons.domain.ids import ContractId
from commons.domain.status import JobStatus
from commons.protocol import Envelope, Message
from commons.substrate.bus import RateLimited

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.community import Community
    from commons.domain.contract import Contract
    from commons.domain.market import Part

MAX_ARTIFACT = 12_000  # characters of work, a playbook or a delivery; longer is refused, never cut off (3 Oct)
MAX_NOTE = 500
FORMAT_REFUSED = "format"  # the Outcome id of a hand-in the format rule refused: the draft needs revising, not resending


def size_problems(text: str) -> list[str]:
    """What's wrong with the length of a piece of work, whatever its part asks: it must fit `MAX_ARTIFACT`. Work used
    to be cut off at the cap without a word, which could drop its last section."""
    return [f"it is {len(text)} characters; the most is {MAX_ARTIFACT}"] if len(text) > MAX_ARTIFACT else []


class CommandBase:
    actor = "scripted"  # the LLM runtime sets "steward"
    why = ""  # a rationale the runtime attaches to the next action, for the decision log

    def __init__(self, world: World, me: Community):
        self.w = world
        self.me = me

    def operator_refusal(self, action: str, args: dict) -> str | None:
        """A rule refusing this action before it runs: the pack's (an action this society doesn't have), then your
        operator's limits. Every command asks it (commands/pipeline.py); so do desk tools and the LLM runtime."""
        with self.w.lock:
            if action in self.w.pack.without:
                return f"this society has no {action.replace('_', ' ')}"
            held = sum(j.prime == self.me.name and j.status == JobStatus.CLAIMED for j in self.w.jobs.values())
            return self.w.operator.check(self.me.name, action, args, held)

    def _send(self, msg: Message) -> bool:
        try:
            self.w.bus.publish(Envelope.seal(self.me.identity, msg, self.w.cycle))
            return True
        except RateLimited:
            return False

    def _use_capacity(self) -> Outcome | None:
        if self.me.capacity <= 0:
            return Outcome(False, "no capacity left this turn: every funded member is busy")
        self.me.capacity -= 1
        return None

    def _contract(self, contract_id: ContractId) -> Contract | None:
        return self.w.contracts.get(contract_id)

    def _size_ok(self, text: str) -> Outcome | None:
        if problems := size_problems(text):
            return Outcome(False, f"refused: {problems[0]}. Shorten it and hand it in again", FORMAT_REFUSED)
        return None

    def _screened(self, kind: str, text: str) -> Outcome | None:
        """The pack's screen (commons/application/screening.py)."""
        why = screen(self.w, self.me.name, kind, text)
        return Outcome(False, why) if why else None

    def _format_ok(self, part: Part, artifact: str) -> Outcome | None:
        """The size cap, then the part's format, by rule (commons/domain/format.py). Scripted stand-ins (quality-tagged)
        are judged by their tag, as the grader judges them; model-written text never carries a tag (the runtime strips
        them)."""
        if (err := self._size_ok(artifact)) is not None:
            return err
        if (err := self._citations_ok(artifact)) is not None:
            return err
        if (err := review_work(self.w, self.me.name, self.actor, artifact)) is not None:
            return err
        if is_tagged(artifact) or not (problems := part.format.problems(artifact)):
            return None
        return Outcome(False, f"refused by the format rule for {part.capability}: {'; '.join(problems)}. "
                              f"Revise it ({part.format.describe()}) and hand it in again", FORMAT_REFUSED)

    def _citations_ok(self, artifact: str) -> Outcome | None:
        """Every [archive: id] the work cites must exist, checked at hand-in so a mistyped id can be fixed (12 Oct: one
        typo, "wcpr-2025-pdf#45" for "wcpr-24-25-pdf#45", failed a whole job at grading). A near miss gets a
        suggestion; the grader's rule still fails anything that reaches it with a citation to nothing."""
        missing = [c for c in archive_citations(artifact) if self.w.archive.get(c) is None]
        if not missing:
            return None
        ids = list(self.w.archive.passages)
        hints = []
        for c in missing[:4]:
            near = difflib.get_close_matches(c, ids, n=1, cutoff=0.85)
            hints.append(f"{c} (did you mean {near[0]}?)" if near else c)
        return Outcome(False, f"refused: the work cites archive passages that don't exist: {'; '.join(hints)}. Cite "
                              "only passages search_archive or read_archive gave you, then hand it in again",
                       FORMAT_REFUSED)

    def _cites_ok(self, cites: tuple[str, ...]) -> Outcome | None:
        unknown = [c for c in cites if c not in self.w.library]
        return Outcome(False, f"unknown playbook(s): {', '.join(unknown)}") if unknown else None
