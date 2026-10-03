"""The golden master: what today's code produces, recorded so a refactor can prove it changed nothing.

A run is captured as five streams, each normalised (sorted keys, no wall-clock times):

    postings   every ledger posting, in order
    telemetry  every telemetry event: kind, cycle, fields
    activity   every activity-log entry
    told       what each co-op was told before each of its turns (the events in its observation)
    summary    the run's summary text

`RUNS` names the runs: scripted societies of both packs on three seeds, and a fake-model live society of each pack.
Fixtures live in tests/golden/fixtures/ as gzipped JSON lines. Regenerating them is a deliberate act:

    uv run python -m tests.golden.update        # only when a behaviour change has been approved
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import tempfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
VOLATILE = {"at", "ms", "elapsed", "seconds", "started", "ended", "time"}  # wall-clock fields, never compared

RUNS = {f"scripted-{pack}-{seed}": (pack, seed, 200, False) for pack in ("earn_online", "tech_for_good") for seed in (0, 3, 7)}
RUNS |= {f"live-fake-{pack}": (pack, 0, 10, True) for pack in ("earn_online", "tech_for_good")}


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float):
        return round(value, 9)
    return value


def _line(obj) -> str:
    return json.dumps(_clean(obj), sort_keys=True, default=str, separators=(",", ":"))


@contextlib.contextmanager
def _recording_turns(world, told: list[str]):
    """Record what each co-op is told, at the start of every turn, by wrapping `turn` on each strategy class.
    Class-level, so forked co-ops (deep copies) are recorded too and behave exactly as before."""
    classes = {type(c.strategy) for c in world.communities.values()}
    originals = {cls: cls.turn for cls in classes}

    def wrap(original):
        def turn(self, obs, act):
            told.append(_line({"cycle": obs.cycle, "coop": obs.name, "events": [e.__dict__ for e in obs.events]}))
            return original(self, obs, act)
        return turn

    for cls, original in originals.items():
        cls.turn = wrap(original)
    try:
        yield
    finally:
        for cls, original in originals.items():
            cls.turn = original


def _build(pack_name: str, seed: int, live: bool, tmp: Path):
    from commons.application.society import Params, World
    from commons.domain.pack import load

    pack = load(pack_name)
    common = dict(seed=seed, activity_path=str(tmp / "activity.jsonl"), ledger_path=str(tmp / "ledger.sqlite"))
    if not live:
        return World(Params(**{**pack.params, **common}), pack=pack)
    from commons.adapters.models import FakeBackend
    from commons.agents.llm.fakes import GOOD_GRADE, competent
    from commons.agents.llm.steward import LLMStrategy
    from commons.application.graders import HybridGrader, LLMGrader
    from commons.application.ventures import LLMAppraiser
    from commons.domain.community import Community

    backend = FakeBackend(respond=lambda *a: GOOD_GRADE, converse=competent)

    def llm(name, caps, charter, members=3, doctrine=""):
        return Community(name, members, caps, LLMStrategy(backend, steward_model="fake", member_model="fake"), charter=charter)

    return World(Params(**{**pack.live, **common, "parallel_turns": False, "grading_workers": 1}),
                 population=pack.live_population(llm), pack=pack,
                 grader=HybridGrader(LLMGrader(backend, model="fake", system=pack.grader_system)),
                 appraiser=LLMAppraiser(backend, model="fake", system=pack.appraiser_system))


def _resume(world, tmp: Path, live: bool):
    """Save the society, then resume it into a new object, reattaching what a save leaves out (as a scheduled run
    would): the fake model for the LLM co-ops, the grader and the appraiser."""
    from commons.application.society import World

    world.save(tmp / "society.save")
    world.activity.close()
    if not live:
        return World.resume(tmp / "society.save")
    from commons.adapters.models import FakeBackend
    from commons.agents.llm.fakes import GOOD_GRADE, competent
    from commons.application.graders import HybridGrader, LLMGrader
    from commons.application.ventures import LLMAppraiser

    backend = FakeBackend(respond=lambda *a: GOOD_GRADE, converse=competent)
    pack = world.pack
    return World.resume(tmp / "society.save", grader=HybridGrader(LLMGrader(backend, model="fake", system=pack.grader_system)),
                        appraiser=LLMAppraiser(backend, model="fake", system=pack.appraiser_system), backend=backend)


def capture(name: str, split: int | None = None) -> dict[str, list[str]]:
    """The run's streams. With `split`, it plays `split` cycles, saves, resumes and plays the rest: the streams must
    be the same as without."""
    from commons.application.services.recorder import summary

    pack, seed, cycles, live = RUNS[name]
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        world = _build(pack, seed, live, tmp)
        telemetry: list[str] = []

        def record(ev):
            telemetry.append(_line({"kind": ev.kind, "cycle": ev.cycle, "fields": ev.fields}))

        world.hub.subscribe(record)
        told: list[str] = []
        with _recording_turns(world, told):
            if split:
                world.run(split)
                world = _resume(world, tmp, live)
                world.hub.subscribe(record)
            world.run(cycles - (split or 0))
        world.ledger.check()
        postings = [_line(row) for row in world.ledger.db.execute(
            "SELECT e.id, e.cycle, e.currency, e.kind, e.memo, p.account, p.amount FROM entries e "
            "JOIN postings p ON p.entry_id = e.id ORDER BY e.id, p.rowid")]
        world.activity.close()
        activity = [_line(json.loads(x)) for x in (tmp / "activity.jsonl").read_text().splitlines()]
    return {"postings": postings, "telemetry": telemetry, "activity": activity, "told": told,
            "summary": summary(world).splitlines()}


def path(name: str) -> Path:
    return FIXTURES / f"{name}.json.gz"


def save(name: str, streams: dict[str, list[str]]) -> None:
    FIXTURES.mkdir(exist_ok=True)
    with gzip.open(path(name), "wt") as f:
        json.dump(streams, f, separators=(",", ":"))


def load(name: str) -> dict[str, list[str]]:
    with gzip.open(path(name), "rt") as f:
        return json.load(f)


def digest(streams: dict[str, list[str]]) -> dict[str, str]:
    return {k: hashlib.sha256("\n".join(v).encode()).hexdigest()[:16] for k, v in sorted(streams.items())}


def first_difference(expected: list[str], actual: list[str]) -> str:
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            return f"line {i}:\n  expected {a[:400]}\n  actual   {b[:400]}"
    return f"lengths differ: expected {len(expected)} lines, got {len(actual)}"
