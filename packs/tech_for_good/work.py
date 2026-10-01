"""The tech-for-good pack's work: questions about problems worth solving, taken apart into four kinds of part.

A job is one subject (a problem or an area, ideally written by you in the society's questions.md) and some of
scout (what already exists), assess (does it work, for whom, at what cost and risk), design (a small pilot) and
write (a brief a funder or council officer could act on).

Until members can search the web (K5), evidence comes from the society's archive or from the model's general
knowledge, so every rubric asks the same thing: cite an archive passage as [archive: <id>] or mark the claim
(unverified). A made-up citation fails the part by rule, before any grading (see the grading service, commons/application/services/grading.py).
"""

from commons.domain.pack import TemplateWorkSource

# Used when a society gives no questions of its own (and by the scripted regression runs).
SUBJECTS = (
    "safe drinking water for rural households",
    "flood warnings for small towns",
    "loneliness among older people living alone",
    "food waste from small shops",
    "literacy support for adult learners",
    "repairs for wheelchairs and mobility aids",
    "heat safety for outdoor workers",
    "digital skills for people looking for work",
    "clean cooking in homes that burn wood or charcoal",
    "mental health support for young people waiting for treatment",
)

EVIDENCE = ("Every factual claim either cites an archive passage as [archive: <id>] or is marked (unverified); "
            "no invented statistics, names or sources.")

TEMPLATES: dict[str, tuple[str, str]] = {  # in this order: same seed, same jobs
    "scout": (
        "Find three distinct existing approaches to {subject}. For each: what it is, who runs it or where it has been "
        "tried, and how it works, in two or three sentences.",
        "Exactly three approaches, numbered; each works by a different mechanism (not three versions of one idea); "
        "each says who runs it or where it has been tried, or says plainly that this is not known. " + EVIDENCE,
    ),
    "assess": (
        "Assess one promising approach to {subject}: the evidence that it works, how feasible it is (cost, skills, "
        "time), who benefits and roughly how many, and its risks. 150 to 300 words.",
        "Four labelled sections: Evidence, Feasibility, Who benefits, Risks. Evidence separates what is known from "
        "what is assumed. Risks names at least two concrete downsides or ways it could fail. 150 to 300 words. "
        + EVIDENCE,
    ),
    "design": (
        "Design a small pilot on {subject} that a volunteer group could run in eight weeks on a small budget.",
        "States the goal, who it serves, at most six steps, the budget and what else it needs, and one measurable "
        "success indicator with how it will be measured; includes a point at which the pilot stops or changes if it "
        "causes harm; realistic for a small volunteer group.",
    ),
    "write": (
        "Write a one-page brief on {subject} for a local funder or council officer: the problem, one recommended "
        "action, its rough cost, and what is still uncertain. 200 to 350 words.",
        "200 to 350 words in plain language, no hype words (revolutionary, game-changing, transformative); recommends "
        "exactly one action; has a section on what is still uncertain. " + EVIDENCE,
    ),
}

WORK_SOURCE = TemplateWorkSource(SUBJECTS, TEMPLATES)
