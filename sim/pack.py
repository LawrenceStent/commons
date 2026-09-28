"""Packs: what one society is *for*. The kernel (everything outside `packs/`) knows how any society works;
a pack says what this one is about.

A pack supplies:
    brief            what the society is for, shown to every steward (a cached block of its prompt)
    capabilities     the skills vocabulary
    work_source      where jobs come from (a `WorkSource`)
    population       the scripted seed co-ops (the regression suite runs against these)
    live_population  the co-ops for a live run, given a factory that makes an LLM strategy
    params / live_params   overrides of the kernel's economy defaults, for scripted and live runs
    grader_system / appraiser_system / member_system   how this society judges and does its work
    grader_cases / venture_cases   hand-labelled calibration sets for its grader and appraiser
    grader_panel     optional lenses (one system prompt each) for a panel of graders; the part gets the median
    scorecard        mission metrics (sim/scorecard.py): what success means for this society, beyond money

Packs are found by name: `load("earn_online")` imports `packs.earn_online` and returns its `PACK`. The
kernel refers to no pack except through `DEFAULT`, the one used when a world is built without saying.
"""

from __future__ import annotations

import importlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from sim.market import MarketJob, Part

if TYPE_CHECKING:
    from society.community import Community

DEFAULT = "earn_online"


class WorkSource(Protocol):
    """Where a society's jobs come from. Called once per job the world posts."""

    def new_job(self, rng: random.Random, job_id: str, cycle: int, reward: int, board_ttl: int, parts: int) -> MarketJob: ...


@dataclass(frozen=True)
class TemplateWorkSource:
    """Jobs made from templates: pick a subject, pick `parts` capabilities, fill each capability's
    (spec, rubric) template with the subject. Enough for any pack whose work is "do these parts for X"."""

    subjects: Sequence[str]
    templates: dict[str, tuple[str, str]]  # capability -> (spec, rubric), each with a {subject} slot
    title: str = "{subject}"

    def new_job(self, rng, job_id, cycle, reward, board_ttl, parts):
        subject = rng.choice(self.subjects)
        caps = sorted(rng.sample(list(self.templates), parts))  # the pack's own order: same seed, same jobs
        return MarketJob(
            id=job_id,
            title=self.title.format(subject=subject),
            reward=reward,
            parts={c: Part(c, self.templates[c][0].format(subject=subject), self.templates[c][1].format(subject=subject))
                   for c in caps},
            posted=cycle,
            deadline=cycle + board_ttl,
        )


@dataclass(frozen=True)
class Pack:
    name: str
    title: str
    brief: str
    capabilities: tuple[str, ...]
    work_source: WorkSource
    population: Callable[[], list[Community]]
    live_population: Callable[[Callable[[str, set[str], str], Community]], list[Community]] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    live_params: dict[str, Any] = field(default_factory=dict)
    grader_system: str | None = None
    appraiser_system: str | None = None
    member_system: str | None = None
    grader_cases: tuple = ()
    venture_cases: tuple = ()
    grader_panel: tuple[str, ...] = ()
    scorecard: tuple = ()


def load(name: str | None = None) -> Pack:
    name = name or DEFAULT
    try:
        module = importlib.import_module(f"packs.{name}")
    except ModuleNotFoundError as e:
        raise ValueError(f"no pack called {name!r} (looked for packs/{name}/)") from e
    return module.PACK
