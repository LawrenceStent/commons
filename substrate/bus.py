"""The bus: one stream per message family, a consumer group per community.

Two backends share one front door (`Bus.publish`), which enforces what the substrate
guarantees regardless of transport: every envelope is signed by a registered sender, and
initiating verbs are rate-limited by the sender's standing in the commons.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Callable

from protocol import FAMILIES, Envelope
from substrate.registry import Registry
from substrate.telemetry import NULL, Hub

# Verbs that fulfil an obligation or report on one are never throttled. Limiting them
# would let a low-reputation party use "I was rate-limited" as an excuse not to deliver.
EXEMPT = {
    ("contract", "award"),
    ("contract", "deliver"),
    ("contract", "settle"),
    ("reputation", "attest"),
    ("reputation", "dispute"),
    ("gate", "request"),
    ("gate", "approve"),
    ("gate", "deny"),
    ("gate", "revoke"),
}


class BadSignature(Exception):
    pass


class RateLimited(Exception):
    pass


def allowance_for(standing: float, base: int) -> int:
    """Messages per cycle. Neutral standing (0.5) gets `base`; the floor is 1, the ceiling 1.5x."""
    return max(1, round(base * min(1.5, max(0.0, 2 * standing - 0.25) / 0.75)))


class Bus:
    def __init__(
        self,
        registry: Registry,
        standing: Callable[[str], float] | None = None,
        base_allowance: int = 12,
        verify: bool = True,
        hub: Hub = NULL,
    ):
        self.hub = hub
        self.registry = registry
        self.standing = standing or (lambda _: 0.5)
        self.base_allowance = base_allowance
        self.verify = verify
        self.cycle = 0
        self._used: dict[str, int] = defaultdict(int)
        self.rejected: dict[str, int] = defaultdict(int)
        self.sent: Counter[str] = Counter()  # per family, since the start
        self.recent: deque[Envelope] = deque(maxlen=500)

    # ── rate limiting ──────────────────────────────────────────
    def begin_cycle(self, cycle: int) -> None:
        self.cycle = cycle
        self._used.clear()

    def allowance(self, sender: str) -> int:
        return allowance_for(self.standing(sender), self.base_allowance)

    def headroom(self, sender: str) -> int:
        return self.allowance(sender) - self._used[sender]

    # ── publishing ─────────────────────────────────────────────
    def publish(self, env: Envelope) -> str:
        if self.verify:
            key = self.registry.key(env.sender)
            if key is None or not env.verify(key):
                raise BadSignature(env.id)
        if (env.family, env.verb) not in EXEMPT:
            if self._used[env.sender] >= self.allowance(env.sender):
                self.rejected[env.sender] += 1
                self.hub.emit("bus.rate_limited", self.cycle, sender=env.sender, family=env.family, verb=env.verb)
                raise RateLimited(f"{env.sender} over allowance at cycle {self.cycle}")
            self._used[env.sender] += 1
        self._append(env)
        self.recent.append(env)
        self.sent[env.family] += 1
        self.hub.emit("bus.publish", self.cycle, sender=env.sender, family=env.family, verb=env.verb,
                      body={k: v for k, v in env.body.items() if k != "artifact"})
        return env.id

    def read(self, family: str, group: str) -> list[Envelope]:
        """Everything on `family` that `group` hasn't consumed yet, in order."""
        raise NotImplementedError

    def _append(self, env: Envelope) -> None:
        raise NotImplementedError


class MemoryBus(Bus):
    """In-process streams. Same semantics as Redis, fast enough for 10k-cycle sims."""

    def __init__(self, *args, max_backlog: int = 5_000, **kw):
        super().__init__(*args, **kw)
        self.max_backlog = max_backlog
        self._streams: dict[str, list[Envelope]] = {f: [] for f in FAMILIES}
        self._cursors: dict[tuple[str, str], int] = defaultdict(int)

    def _append(self, env: Envelope) -> None:
        self._streams[env.family].append(env)

    def read(self, family: str, group: str) -> list[Envelope]:
        stream = self._streams[family]
        start = self._cursors[(family, group)]
        self._cursors[(family, group)] = len(stream)
        return stream[start:]

    def compact(self) -> None:
        """Drop envelopes every known group has consumed, then cap each stream at `max_backlog`
        (like Redis MAXLEN): a family nobody reads, or a group that has stopped reading, must
        not grow memory without bound. A lagging group loses the oldest envelopes."""
        for family, stream in self._streams.items():
            groups = [n for (f, _), n in self._cursors.items() if f == family]
            done = min(groups) if groups else 0
            done = max(done, len(stream) - self.max_backlog)
            if done > 0:
                del stream[:done]
                for key in list(self._cursors):
                    if key[0] == family:
                        self._cursors[key] = max(0, self._cursors[key] - done)


class RedisBus(Bus):
    """Redis Streams: `commons:<family>` with a consumer group per community."""

    def __init__(self, *args, url: str = "redis://localhost:6379/0", prefix: str = "commons", **kw):
        import redis

        super().__init__(*args, **kw)
        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.prefix = prefix
        self._groups: set[tuple[str, str]] = set()

    def _stream(self, family: str) -> str:
        return f"{self.prefix}:{family}"

    def _append(self, env: Envelope) -> None:
        self.r.xadd(self._stream(env.family), {"env": env.model_dump_json()})

    def _ensure_group(self, family: str, group: str) -> None:
        if (family, group) in self._groups:
            return
        import redis

        try:
            self.r.xgroup_create(self._stream(family), group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._groups.add((family, group))

    def read(self, family: str, group: str) -> list[Envelope]:
        self._ensure_group(family, group)
        stream = self._stream(family)
        out: list[Envelope] = []
        while True:
            resp = self.r.xreadgroup(group, group, {stream: ">"}, count=500)
            if not resp:
                return out
            ids = []
            for _, entries in resp:
                for msg_id, fields in entries:
                    out.append(Envelope.model_validate_json(fields["env"]))
                    ids.append(msg_id)
            self.r.xack(stream, group, *ids)
