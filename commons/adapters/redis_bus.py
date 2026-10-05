"""The bus on Redis Streams, for societies that run across processes. The in-memory bus is commons/substrate/bus.py."""

from __future__ import annotations

from typing import Any

from commons.protocol import Envelope
from commons.substrate.bus import Bus


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
            resp: Any = self.r.xreadgroup(group, group, {stream: ">"}, count=500)  # [(stream, [(id, fields)])]
            if not resp:
                return out
            ids = []
            for _, entries in resp:
                for msg_id, fields in entries:
                    out.append(Envelope.model_validate_json(fields["env"]))
                    ids.append(msg_id)
            self.r.xack(stream, group, *ids)

