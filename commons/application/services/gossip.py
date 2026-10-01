"""Gossip: every few cycles, each co-op relays some of its first-hand beliefs to a few others, discounted, so news of a
defector travels faster than its victims can each find out alone."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.protocol.reputation import Gossip

if TYPE_CHECKING:
    from commons.application.society import World


class GossipService:
    def __init__(self, world: World):
        self.w = world

    def run(self) -> None:
        for c in self.w.active():
            if not c.strategy.gossips:
                continue
            beliefs = sorted(self.w.rep.beliefs(c.name), key=lambda b: -b[3])[: self.w.params.gossip_fanout]
            for subject, cap, score, n in beliefs:
                self.w.send(c, Gossip(subject=subject, capability=cap, score=round(score, 4), evidence=round(n, 3)))
        # every community consumes the reputation stream through its own consumer group
        heard = 0
        for listener in self.w.communities.values():
            for env in self.w.bus.read("reputation", listener.name):
                if env.verb == "gossip":
                    g = env.open()
                    self.w.rep.hear(listener.name, env.sender, g.subject, g.capability, g.score, g.evidence)
                    heard += 1
        self.w.hub.emit("reputation.gossip", self.w.cycle, heard=heard)
