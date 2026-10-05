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
    scorecard        mission metrics (commons/domain/scorecard.py): what success means for this society, beyond money
    desk / live_desk optional: the pack's own tools and state, when its work isn't jobs (commons/domain/desk.py)
    without          kernel actions this society doesn't have (a trading desk has no job board): not offered, refused
    screen           optional: a rule over what enters the society, by kind: "brief" and "question" at founding,
                     "web_search" and "web_fetch" before the gate, "work" at hand-in. It returns why it refuses, or
                     None. With halt_on_screen, a refused attempt during a run also halts the society

Packs are found by name: `load("earn_online")` imports `packs.earn_online` and returns its `PACK`. The
kernel refers to no pack except through `DEFAULT`, the one used when a world is built without saying.
"""

from __future__ import annotations

import importlib
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from commons.domain.format import Format
from commons.domain.ids import JobId
from commons.domain.market import MarketJob, Part
from commons.domain.money import Micros

if TYPE_CHECKING:
    from commons.domain.community import Community
    from commons.domain.desk import Desk

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

    def new_job(self, rng: random.Random, job_id: JobId, cycle: int, reward: Micros, board_ttl: int, parts: int) -> MarketJob: ...


@dataclass(frozen=True)
class TemplateWorkSource:
    """Jobs made from templates: pick a subject, pick `parts` capabilities, fill each capability's
    (spec, rubric) template with the subject. Enough for any pack whose work is "do these parts for X"."""

    subjects: Sequence[str]
    templates: dict[str, tuple[str, str]]  # capability -> (spec, rubric), each with a {subject} slot
    title: str = "{subject}"
    formats: dict[str, Format] = field(default_factory=dict)  # capability -> what its text must look like, by rule
    independent: frozenset[str] = frozenset()  # capabilities someone other than the job's own co-ops must do

    def new_job(self, rng, job_id, cycle, reward, board_ttl, parts):
        subject = rng.choice(self.subjects)
        caps = sorted(rng.sample(list(self.templates), parts))  # the pack's own order: same seed, same jobs
        return MarketJob(
            id=job_id,
            title=self.title.format(subject=subject),
            reward=reward,
            parts={c: Part(c, self.templates[c][0].format(subject=subject), self.templates[c][1].format(subject=subject),
                           format=self.formats.get(c, Format()), independent=c in self.independent) for c in caps},
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
    desk: Callable[[int], Desk] | None = None  # the pack's own tools and state (domain/desk.py), from the run's seed
    live_desk: Callable[[int], Desk] | None = None  # the same for live runs (live data); defaults to `desk`
    without: frozenset[str] = frozenset()  # kernel actions this society doesn't have: not offered, refused by rule
    screen: Callable[[str, str], str | None] | None = None  # (kind, text) -> why it's refused; see `screened`
    halt_on_screen: bool = False  # a screened attempt halts the society until you reset it

    @property
    def live(self) -> dict[str, Any]:
        """The settings for a live run: the live economy, with this pack's overrides."""
        return {**LIVE_ECONOMY, **self.live_params}


def screened(pack: Pack, kind: str, text: str) -> str | None:
    """Why the pack's screen refuses `text` of `kind`, or None (no screen, or it passes)."""
    return pack.screen(kind, text) if pack.screen else None


def load(name: str | None = None) -> Pack:
    name = name or DEFAULT
    try:
        module = importlib.import_module(f"packs.{name}")
    except ModuleNotFoundError as e:
        raise ValueError(f"no pack called {name!r} (looked for packs/{name}/)") from e
    return module.PACK


def default_population() -> list[Community]:
    """The default pack's scripted co-ops."""
    return load().population()
