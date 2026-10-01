"""How many members a co-op wakes each cycle, for any agent: enough for the work in hand plus a little for new
business, within what's free after commitments, and always one if there are promises to keep and a purse to keep them
with. Waking is paid for (upkeep), so it's a decision; this is the default one."""

from __future__ import annotations

from collections.abc import Callable

from commons.application.observation import Observation

Cost = Callable[[Observation, str], int]  # what doing one part of a capability costs this co-op


def default_cost(obs: Observation, capability: str) -> int:
    """The market's going rate for a part, 30% less with a playbook for it in the library."""
    base = int(obs.params.get("work_cost", 25_000))
    return round(base * (0.7 if any(p.capability == capability for p in obs.library) else 1.0))


def free(obs: Observation, cost: Cost = default_cost) -> int:
    """Purse minus everything already promised: remainders owed, work won, and the rest of the jobs it's prime on.
    Committing past this is how a co-op spirals into default."""
    sub_share = obs.params.get("sub_share", 0.4)
    promised = obs.owed + sum(cost(obs, c.capability) for c in obs.to_deliver)
    for job in obs.my_jobs:
        for p in job.parts:
            if p.done or p.pending in ("awarded", "delivered"):
                continue
            promised += cost(obs, p.capability) if p.capability in obs.capabilities else round(job.reward * sub_share)
    return obs.purse - promised


def members_to_wake(obs: Observation, cost: Cost = default_cost) -> int:
    per = int(obs.params.get("actions_per_member", 2))
    upkeep = int(obs.params.get("upkeep", 8_000))
    work = len(obs.to_deliver) + sum(1 for j in obs.my_jobs for p in j.parts if not p.done and p.capability in obs.capabilities)
    new_business = 2 if obs.board or obs.open_contracts else 0
    want = max(1, -(-(work + new_business) // per))
    afford = max(0, free(obs, cost)) // upkeep
    return max(1 if obs.purse >= upkeep else 0, min(want, afford))
