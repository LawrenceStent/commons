"""Identifiers. NewTypes: strings at run time, named kinds of string to a reader and a type checker."""

from typing import NewType

JobId = NewType("JobId", str)  # "J12" (posted), "V3" (a venture's job)
ContractId = NewType("ContractId", str)  # "<job id>.<capability>.<n>"
ProposalId = NewType("ProposalId", str)
PlaybookId = NewType("PlaybookId", str)
PassageId = NewType("PassageId", str)  # "<file stem>#<n>"
VentureId = NewType("VentureId", str)
IdeaId = NewType("IdeaId", str)
GoalId = NewType("GoalId", str)
DraftId = NewType("DraftId", str)


class Sequences:
    """Numbered ids, one counter per kind ("job", "venture", "plan", "proposal"): `next(kind)` is 1, 2, 3, …"""

    def __init__(self):
        self._n: dict[str, int] = {}

    def next(self, kind: str) -> int:
        self._n[kind] = self._n.get(kind, 0) + 1
        return self._n[kind]
