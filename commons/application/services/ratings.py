"""Your ratings, applied: each new rating of a sampled piece of work is first-hand evidence about whoever did each part
(observer "operator"), and the co-op is told. The files are commons/application/ratings.py's."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.domain.ratings import EVIDENCE

if TYPE_CHECKING:
    from commons.application.society import World


class RatingDesk:
    def __init__(self, world: World):
        self.w = world

    def apply(self) -> None:
        """Your new ratings (commons/application/ratings.py): first-hand evidence about whoever did each part. Under the lock."""
        if not self.w.ratings:
            return
        for r in self.w.ratings.reload():
            sample = self.w.ratings.samples[r.id]
            for cap, part in sample["parts"].items():
                if part["by"] in self.w.communities:
                    self.w.rep.attest("operator", part["by"], cap, EVIDENCE[r.rating])
                    self.w.tell(part["by"], "rated", f"the operator rated your {cap} for {sample['job']} {r.rating}/3"
                               + (f": {r.note}" if r.note else ""), sample["job"])
            self.w.hub.emit("operator.rating", self.w.cycle, id=r.id, job=sample["job"], rating=r.rating, note=r.note)
