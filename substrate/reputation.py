"""Reputation: direct experience plus discounted gossip, decaying, scoped by capability.

Beliefs are beta-distribution evidence counts (good, bad) on top of a uniform prior,
so an unknown party scores 0.5 and every observation moves the score less than the last.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from substrate.telemetry import NULL, Hub

Key = tuple[str, str, str]  # (observer, subject, capability)


@dataclass
class Evidence:
    good: float = 0.0
    bad: float = 0.0

    @property
    def n(self) -> float:
        return self.good + self.bad

    def score(self) -> float:
        return (1 + self.good) / (2 + self.n)


class Reputation:
    def __init__(self, decay: float = 0.995, gossip_discount: float = 0.5, bad_memory: float = 4.0, hub: Hub = NULL):
        self.hub = hub
        self.cycle: int | None = None  # set by the world, for telemetry only
        self.decay = decay
        # Bad evidence fades `bad_memory` times more slowly than good. With symmetric decay
        # a defector's record fades back over the refusal line, it scams once, and repeats.
        self.bad_decay = decay ** (1 / bad_memory)
        self.gossip_discount = gossip_discount
        self.direct: dict[Key, Evidence] = defaultdict(Evidence)
        # listener's second-hand view, kept per source so a source's newest relay
        # replaces its last one instead of compounding into certainty
        self.indirect: dict[Key, dict[str, Evidence]] = defaultdict(dict)

    # ── recording ──────────────────────────────────────────────
    def attest(self, observer: str, subject: str, capability: str, outcome: float) -> None:
        if observer == subject:
            return
        e = self.direct[(observer, subject, capability)]
        e.good += outcome
        e.bad += 1 - outcome
        self.hub.emit("reputation.attest", self.cycle, observer=observer, subject=subject, capability=capability, outcome=outcome)

    def hear(self, listener: str, source: str, subject: str, capability: str, score: float, evidence: float) -> None:
        """Take in gossip, weighted by how much the listener trusts the source overall."""
        if listener in (source, subject):
            return
        weight = self.gossip_discount * self.trust(listener, source)
        n = min(evidence, 10.0) * weight
        self.indirect[(listener, subject, capability)][source] = Evidence(n * score, n * (1 - score))

    def tick(self) -> None:
        for e in self._all_evidence():
            e.good *= self.decay
            e.bad *= self.bad_decay

    def _all_evidence(self):
        yield from self.direct.values()
        for by_source in self.indirect.values():
            yield from by_source.values()

    # ── reading ────────────────────────────────────────────────
    def score(self, observer: str, subject: str, capability: str) -> float:
        d = self.direct.get((observer, subject, capability), Evidence())
        heard = self.indirect.get((observer, subject, capability), {}).values()
        return Evidence(d.good + sum(e.good for e in heard), d.bad + sum(e.bad for e in heard)).score()

    def trust(self, observer: str, subject: str) -> float:
        """Observer's capability-agnostic view of subject, from direct dealings only."""
        good = bad = 0.0
        for (o, s, _), e in self.direct.items():
            if o == observer and s == subject:
                good += e.good
                bad += e.bad
        return Evidence(good, bad).score()

    def standing(self, subject: str) -> float:
        """The commons' aggregate view: all first-hand evidence about subject, pooled."""
        good = bad = 0.0
        for (o, s, _), e in self.direct.items():
            if s == subject:
                good += e.good
                bad += e.bad
        return Evidence(good, bad).score()

    def beliefs(self, observer: str) -> list[tuple[str, str, float, float]]:
        """(subject, capability, score, evidence) for everything observer knows first-hand."""
        return [
            (s, c, e.score(), e.n)
            for (o, s, c), e in self.direct.items()
            if o == observer and e.n >= 0.5
        ]
