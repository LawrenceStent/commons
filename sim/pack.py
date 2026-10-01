"""Packs: what one society is *for*. The kernel (everything outside `packs/`) knows how any society works;
a pack says what this one is about.

A pack supplies:
    brief            what the society is for, shown to every steward (a cached block of its prompt)
    capabilities     the skills vocabulary
    work_source      where jobs come from (a `WorkSource`)
    population       the scripted seed co-ops (the regression suite runs against these)
    live_population  the co-ops for a live run, given a factory that makes an LLM strategy
    params           overrides of the kernel's defaults for scripted runs
    live_params      overrides of the live economy (`LIVE_ECONOMY`) for live runs; `pack.live` is the result
    grader_system / appraiser_system / member_system   how this society judges and does its work
    grader_cases / venture_cases   hand-labelled calibration sets for its grader and appraiser
    grader_panel     optional lenses (what each grader of a panel looks hardest at); the part gets the median
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

# The live economy, for any pack, calibrated on the 1.5 local runs: a steward call costs about 4,500 µcr (about 10,000
# when the model reasons) and handling a job takes a few turns plus contractors. At the scripted defaults (reward 80k)
# thinking bankrupted every LLM co-op within three cycles. Spawn and learn were out of reach (1.5M and 2.5M against a
# 400k purse) until 27 Sep.
LIVE_ECONOMY: dict[str, Any] = dict(
    job_reward=400_000, purse_seed=400_000, treasury_seed=10_000_000, treasury_reserve=10_000_000,
    upkeep=2_000, basic_budget=1_500, floor_cap=4_000, work_cost=40_000, publish_cost=60_000,
    spawn_fee=250_000, learn_cost=800_000, audit_cost=20_000, venture_fee=20_000,
    board_ttl=5, job_ttl=12, bid_window=4, deliver_ttl=5, review_ttl=3, dispute_window=4)


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

    @property
    def live(self) -> dict[str, Any]:
        """The settings for a live run: the live economy, with this pack's overrides."""
        return {**LIVE_ECONOMY, **self.live_params}


def load(name: str | None = None) -> Pack:
    name = name or DEFAULT
    try:
        module = importlib.import_module(f"packs.{name}")
    except ModuleNotFoundError as e:
        raise ValueError(f"no pack called {name!r} (looked for packs/{name}/)") from e
    return module.PACK
