"""The steward's tools: the actions executor, described for a model.

`review` and `dispute` are gone: the grader judges every delivery (option B, 26 Sep).

Sorted by name and never generated per turn, so the tool list is byte-identical on every call and
sits inside the cached prefix. Two tools belong to the runtime rather than the executor:
`commission` (a member writes a draft) and `end_turn`.

Descriptions are the only instructions a tool gets, so each says what it does, what it costs,
and when it will be refused.
"""

from __future__ import annotations

from typing import Any


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
IDS = {"type": "array", "items": {"type": "string"}}

_TOOLS: list[dict[str, Any]] = [
    {"name": "accept_merge", "description": "Accept a merge offer addressed to you: the proposer's members, purse, "
     "capabilities and playbooks join your community. Refused if they still have work in flight or the total would "
     "exceed the member limit.", "input_schema": _obj({"proposal_id": S}, ["proposal_id"])},
    {"name": "announce", "description": "Offer a part of a job you are prime on to other communities. Bids arrive "
     "from their next turns. max_price is the most you'll pay (µcr); advance_frac (0 to 1) is paid on award. Free "
     "to post but rate-limited by your standing.", "input_schema": _obj(
        {"job_id": S, "capability": S, "max_price": I, "advance_frac": N}, ["job_id", "capability", "max_price", "advance_frac"])},
    {"name": "attest", "description": "Rate the prime of a closed contract where you were the contractor: 1.0 good "
     "counterparty, 0.0 bad. Once per contract.", "input_schema": _obj({"contract_id": S, "outcome": N}, ["contract_id", "outcome"])},
    {"name": "award", "description": "Award one of your announcements to a bidder. Pays the advance immediately. "
     "Not allowed in the cycle you announced.", "input_schema": _obj({"contract_id": S, "bidder": S}, ["contract_id", "bidder"])},
    {"name": "bid", "description": "Bid on another community's open contract for a capability you have. Uses one "
     "capacity. price in µcr, at most the contract's max.", "input_schema": _obj({"contract_id": S, "price": I}, ["contract_id", "price"])},
    {"name": "claim", "description": "Ask for a job on the board. Claims are allocated at the end of the cycle to the "
     "most trusted, best-fitting claimant, not the first. The winner posts a bond (returned when the job is paid, lost "
     "if it fails) and must submit every part by the deadline. Uses one capacity.",
     "input_schema": _obj({"job_id": S}, ["job_id"])},
    {"name": "commission", "description": "Have an awake member write the work for a part, for a job you are prime "
     "on (ref = job id) or a contract you won (ref = contract id). Returns a draft id and a preview. Costs a model "
     "call, charged to your purse. Optionally pass playbook_id to work from a library playbook; the draft then "
     "cites it. Use the draft with do_part or deliver.", "input_schema": _obj(
        {"ref": S, "capability": S, "instructions": S, "playbook_id": S}, ["ref", "capability", "instructions"])},
    {"name": "deliver", "description": "Deliver a draft for a contract you won. Uses one capacity. The prime then "
     "reviews it.", "input_schema": _obj({"contract_id": S, "draft_id": S}, ["contract_id", "draft_id"])},
    {"name": "do_part", "description": "Submit a draft as a part of a job you are prime on, for a capability you "
     "have. Uses one capacity. When every part is in, the job goes to the grader.",
     "input_schema": _obj({"job_id": S, "capability": S, "draft_id": S}, ["job_id", "capability", "draft_id"])},
    {"name": "end_turn", "description": "Finish your turn.", "input_schema": _obj({}, [])},
    {"name": "fork", "description": "Split `members` of your members off into a new community called `name` with "
     "the listed capabilities (a subset of yours) and a share of your purse. Uses one capacity.",
     "input_schema": _obj({"name": S, "members": I, "capabilities": IDS, "charter": S}, ["name", "members", "capabilities", "charter"])},
    {"name": "idea", "description": "Record an idea worth remembering: an opportunity, a method, a partner. Free.",
     "input_schema": _obj({"title": S, "detail": S}, ["title"])},
    {"name": "set_goal", "description": "Set a goal with a checklist of steps (at most 12). Optionally the idea it "
     "came from. Shown to you every turn until done or dropped. Free.",
     "input_schema": _obj({"title": S, "steps": IDS, "idea_id": S}, ["title", "steps"])},
    {"name": "update_goal", "description": "Tick a step of a goal done (step is 1-based), add a note, or set the "
     "goal's status to done or dropped. Free.", "input_schema": _obj(
        {"goal_id": S, "step": I, "done": B, "note": S, "status": {"type": "string", "enum": ["active", "done", "dropped"]}},
        ["goal_id"])},
    {"name": "propose_venture", "description": "Propose work of your own that the market doesn't "
     "list yet, in 1-3 parts, each a different capability with a spec and a rubric a grader can check. Costs a small "
     "fee. Appraised at the start of next cycle; if approved it becomes your own job, with a reward the market sets "
     "from the appraisal. Refused at once if it breaks a rule (standing, job limit, a copy of existing work, vague parts).",
     "input_schema": _obj({"title": S, "pitch": S, "idea_id": S, "parts": {"type": "array", "items": _obj(
         {"capability": S, "spec": S, "rubric": S}, ["capability", "spec", "rubric"])}}, ["title", "pitch", "parts"])},
    {"name": "learn", "description": "Buy a capability you lack. Expensive, and more so the more you have. Cheaper "
     "with a playbook_id for that capability, whose author earns a royalty. Uses one capacity.",
     "input_schema": _obj({"capability": S, "playbook_id": S}, ["capability"])},
    {"name": "note", "description": "Write a short journal entry for your future turns (max 500 characters). Free.",
     "input_schema": _obj({"text": S}, ["text"])},
    {"name": "propose_merge", "description": "Offer to merge your community into `target`. They must accept. Uses "
     "one capacity.", "input_schema": _obj({"target": S}, ["target"])},
    {"name": "propose_spawn", "description": "Ask to add a member with the given role. Needs a second from another "
     "community within a few cycles; the spawn fee is charged then. Uses one capacity.",
     "input_schema": _obj({"role": S}, ["role"])},
    {"name": "publish", "description": "Publish a playbook for a capability you have: a title and the method as "
     "text. Costs the publish fee. You earn royalties when paid work cites it.",
     "input_schema": _obj({"capability": S, "title": S, "text": S}, ["capability", "title", "text"])},
    {"name": "read_playbook", "description": "Read a playbook's full text. Free.", "input_schema": _obj({"playbook_id": S}, ["playbook_id"])},
    {"name": "retire", "description": "Drop one member. No refund.", "input_schema": _obj({}, [])},
    {"name": "second_spawn", "description": "Second another community's spawn request. Free.",
     "input_schema": _obj({"proposal_id": S}, ["proposal_id"])},
]

# every tool may carry a short rationale; the runtime strips it and writes it to the decision log
for _t in _TOOLS:
    _t["input_schema"]["properties"]["why"] = {"type": "string", "description": "optional: why, in one sentence"}

TOOLS: list[dict[str, Any]] = sorted(_TOOLS, key=lambda t: t["name"])
NAMES = frozenset(t["name"] for t in TOOLS)
