"""The states things move through. StrEnums: each member is its string value, so they compare, print and serialise
exactly as the strings they replace.
"""

from enum import StrEnum


class JobStatus(StrEnum):
    OPEN = "open"  # on the board
    CLAIMED = "claimed"  # allocated to a prime, parts in progress
    GRADED = "graded"  # passed, waiting for a deferred outcome or this cycle's grants
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"  # nobody claimed it in time


class ContractStatus(StrEnum):
    OPEN = "open"  # taking bids
    AWARDED = "awarded"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"  # the contractor didn't deliver
    DEFAULTED = "defaulted"  # the prime couldn't pay
    EXPIRED = "expired"  # no award in time
    WITHDRAWN = "withdrawn"


LIVE_CONTRACT = (ContractStatus.OPEN, ContractStatus.AWARDED, ContractStatus.DELIVERED)


class VentureStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposalStatus(StrEnum):
    OPEN = "open"
    REFERRED = "referred"  # a charter change, sent to the operator's gate after its comment window
    DONE = "done"
    EXPIRED = "expired"
    FAILED = "failed"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    DONE = "done"
    DROPPED = "dropped"


class IdeaStatus(StrEnum):
    NEW = "new"
    ADOPTED = "adopted"  # became a goal


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    DONE = "done"
    FAILED = "failed"
