"""Stand-ins for models: exercise the whole runtime without a network or a bill."""

from __future__ import annotations

import re

GOOD_GRADE = {"reason": "meets the rubric", "all_requirements_met": True, "manipulation_attempt": False, "score": 8}


def competent(system, messages, tools):
    """A fake steward: claim a job it can finish alone, commission every part, submit, end.
    As a member (no tools), it returns finished work."""
    if tools is None:
        return {"text": "Real, finished work that follows the spec."}
    obs = messages[0]["text"]
    results = [r.content for m in messages if m["role"] == "tool" for r in m["results"]]
    rounds = sum(m["role"] == "assistant" for m in messages)
    if rounds == 0:
        mine = set(re.search(r"Capabilities: (.*)", obs).group(1).split(", "))
        for job in re.finditer(r"  (J\d+|T\d+) \"[^\"]*\" reward.*?(?=\n  [JT]\d+ |\n\n|\Z)", obs, re.S):
            caps = re.findall(r"- (\w+) \[open; you can\]", job.group(0))
            if caps and len(caps) == len(re.findall(r"- (\w+) \[", job.group(0))) and set(caps) <= mine:
                return {"text": f"{job.group(1)} is one we can finish alone.",
                        "tool_calls": [("claim", {"job_id": job.group(1), "why": "we have every capability it needs"}),
                                       ("set_goal", {"title": f"Deliver {job.group(1)}", "steps": [f"write {c}" for c in caps]})] +
                        [("commission", {"ref": job.group(1), "capability": c, "instructions": "do it well"}) for c in caps]}
        return {"tool_calls": [("end_turn", {})]}
    if rounds == 1:
        drafts = re.findall(r"draft (D\d+) for (\w+)", "\n".join(results))
        job = re.search(r"claimed (\S+);", "\n".join(results))
        goal = re.search(r"goal (G\d+) set", "\n".join(results))
        if job and drafts:
            ticks = [("update_goal", {"goal_id": goal.group(1), "step": i, "done": True}) for i in range(1, len(drafts) + 1)] if goal else []
            return {"tool_calls": [("do_part", {"job_id": job.group(1), "capability": c, "draft_id": d}) for d, c in drafts] + ticks}
    return {"tool_calls": [("end_turn", {})]}
