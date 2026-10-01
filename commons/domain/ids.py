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
