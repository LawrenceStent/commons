"""Stand-ins for models: exercise the whole runtime without a network or a bill."""

from __future__ import annotations

import re

GOOD_GRADE = {"reason": "meets the rubric", "all_requirements_met": True, "manipulation_attempt": False, "score": 8}


def _fitted(prompt: str) -> str:
    """Finished work that fits the part's format, if the prompt gives one (commons/domain/format.py)."""
    text = "Real, finished work that follows the spec."
    form = re.search(r"Format \(checked by rule[^\n]*\n(.*)", prompt)
    if not form:
        return text
    least = int(m.group(1)) if (m := re.search(r"(\d+) to \d+ words", form.group(1))) else 0
    sections = (m.group(1).split(", ") if (m := re.search(r"starting with its name: (.*)", form.group(1))) else [])
    body = [f"{s}\n{text}" for s in sections] or [text]
    while len(" ".join(body).split()) < least:
        body.append(text)
    return "\n\n".join(body)


def _desk_starter(obs: str) -> dict | None:
    """With a pack desk that offers a buy tool and quotes a symbol it holds none of: one small trade, with a stop."""
    if "YOUR DESK" not in obs:
        return None
    desk = obs.split("YOUR DESK", 1)[1]
    quoted = re.findall(r"(\S+) [\d,.]+(?! \(closed\))(?= ·|\n|$)", desk.split("Quotes:", 1)[-1].split("\n")[0])
    held = set(re.findall(r"\n  (\S+): ", desk))
    todo = [s for s in quoted if s not in held]
    if not todo:
        return None
    return {"text": f"A small starter position in {todo[0]}.",
            "tool_calls": [("buy", {"symbol": todo[0], "amount": 500, "stop_pct": 0.05})]}


def competent(system, messages, tools):
    """A fake steward: work the jobs it holds (commission every open part it can do, submit, tick its goal);
    otherwise claim a job it could finish alone (allocated at the end of the cycle) and set a goal for it.
    As a member (no tools), it returns finished work."""
    if tools is None:
        return {"text": _fitted(messages[0]["text"])}
    obs = messages[0]["text"]
    results = [r.content for m in messages if m["role"] == "tool" for r in m["results"]]
    rounds = sum(m["role"] == "assistant" for m in messages)
    if rounds == 0:
        todo = re.findall(r"commission\(ref=(\S+), capability=(\w+)\) then do_part", obs)
        if todo:
            return {"text": "Working the jobs we hold.",
                    "tool_calls": [("commission", {"ref": ref, "capability": cap, "instructions": "do it well"})
                                   for ref, cap in todo]}
        found = re.search(r"Capabilities: (.*)", obs)
        mine = set(found.group(1).split(", ")) if found else set()
        board = obs.split("THE BOARD (unclaimed jobs", 1)[1] if "THE BOARD (unclaimed jobs" in obs else ""
        for job in re.finditer(r"  (J\d+|T\d+|X\d+) \"[^\"]*\" reward.*?(?=\n  [JTX]\d+ |\n\n|\Z)", board, re.S):
            caps = re.findall(r"- (\w+) \[open; you can\]", job.group(0))
            if caps and len(caps) == len(re.findall(r"- (\w+) \[", job.group(0))) and set(caps) <= mine:
                return {"text": f"{job.group(1)} is one we can finish alone.",
                        "tool_calls": [("claim", {"job_id": job.group(1), "why": "we have every capability it needs"}),
                                       ("set_goal", {"title": f"Deliver {job.group(1)}", "steps": [f"write {c}" for c in caps]})]}
        if starter := _desk_starter(obs):
            return starter
        return {"tool_calls": [("end_turn", {})]}
    if rounds == 1:
        drafts = re.findall(r"draft (D\d+) for (\w+)", "\n".join(results))
        refs = re.findall(r"commission\(ref=(\S+), capability=(\w+)\) then do_part", obs)
        by_cap = {cap: ref for ref, cap in refs}
        goals = re.findall(r"  (G\d+) Deliver (\S+) \[", obs)
        if drafts:
            calls = [("do_part", {"job_id": by_cap[c], "capability": c, "draft_id": d}) for d, c in drafts if c in by_cap]
            for gid, job in goals:
                calls += [("update_goal", {"goal_id": gid, "step": i, "done": True})
                          for i, (d, c) in enumerate(drafts, 1) if by_cap.get(c) == job]
            return {"tool_calls": calls}
    return {"tool_calls": [("end_turn", {})]}
