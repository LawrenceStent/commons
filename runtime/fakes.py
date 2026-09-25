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
                return {"tool_calls": [("claim", {"job_id": job.group(1)})] +
                        [("commission", {"ref": job.group(1), "capability": c, "instructions": "do it well"}) for c in caps]}
        return {"tool_calls": [("end_turn", {})]}
    if rounds == 1:
        drafts = re.findall(r"draft (D\d+) for (\w+)", "\n".join(results))
        job = re.search(r"claimed (\S+);", "\n".join(results))
        if job and drafts:
            return {"tool_calls": [("do_part", {"job_id": job.group(1), "capability": c, "draft_id": d}) for d, c in drafts]}
    return {"tool_calls": [("end_turn", {})]}
