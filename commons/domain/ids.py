"""Identifiers: aliases of str, names for readers (NewTypes until R13, 5 Oct: ids arrive as plain strings from tool
calls and messages, so a checker demanded a wrapper at every boundary)."""

from typing import TypeAlias

JobId: TypeAlias = str  # "J12" (posted), "V3" (a venture's job)
ContractId: TypeAlias = str  # "<job id>.<capability>.<n>"
ProposalId: TypeAlias = str
PlaybookId: TypeAlias = str
PassageId: TypeAlias = str  # "<file stem>#<n>"
VentureId: TypeAlias = str
IdeaId: TypeAlias = str
GoalId: TypeAlias = str
DraftId: TypeAlias = str


class Sequences:
    """Numbered ids, one counter per kind ("job", "venture", "plan", "proposal"): `next(kind)` is 1, 2, 3, …"""

    def __init__(self):
        self._n: dict[str, int] = {}

    def next(self, kind: str) -> int:
        self._n[kind] = self._n.get(kind, 0) + 1
        return self._n[kind]
