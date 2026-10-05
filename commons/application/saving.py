"""Saving a society and resuming it, so a long run can be played a cycle at a time on a schedule (K6).

A save is the society's state, pickled. What belongs to the process that ran it stays out: the lock, the hub's
subscribers, open files, and whatever talks to the outside (the grader, the appraiser, the web, each model-backed
co-op's backend). Resuming reattaches those from the new run's settings. The ledger stays in its file; the save keeps
its balances, and resuming refuses a ledger that changed since.

Proof (tests/application/test_save_and_resume.py): every golden run, split in half by a save and a resume, is the
same run, stream for stream. A save is only for resuming with the same code: it is not an archive format.
"""

from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from commons.domain.pack import load as load_pack

if TYPE_CHECKING:
    from commons.application.ports import ModelBackend, WebPort
    from commons.application.society import Society
    from commons.domain.pack import Pack

DETACHED = ("lock", "grader", "appraiser", "web", "pack")  # rebuilt or reattached when the society resumes


def state_of(w: Society) -> dict[str, Any]:
    """The pack is code, not state: the save keeps its name, and resuming loads it."""
    return {**{k: v for k, v in w.__dict__.items() if k not in DETACHED}, "pack_name": w.pack.name}


def restore(w: Society, state: dict[str, Any]) -> None:
    w.__dict__.update(state)
    w.lock = threading.RLock()
    w.__dict__.update(grader=None, appraiser=None, web=None, pack=None)  # attached by `resume`


def save(w: Society, path: str | Path) -> None:
    """Write the save beside its final name, then move it into place, so a crash never leaves half a save."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with w.lock, open(tmp, "wb") as f:
        pickle.dump(w, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def resume(path: str | Path, *, grader=None, appraiser=None, web: WebPort | None = None,
           backend: ModelBackend | None = None, pack: Pack | None = None) -> Society:
    """The society saved at `path`, with the outside reattached: given, or the defaults its settings imply. Every
    co-op whose agent needs a model gets `backend`. The pack is loaded by the name the save recorded, unless given."""
    with open(path, "rb") as f:
        w = pickle.load(f)
    w.pack = pack or load_pack(w.__dict__.pop("pack_name"))
    w.__dict__.pop("pack_name", None)
    w.attach(grader, appraiser, web)
    w.activity.watch(w.hub)
    for c in w.communities.values():
        if attach := getattr(c.strategy, "attach", None):
            attach(backend)
    return w
