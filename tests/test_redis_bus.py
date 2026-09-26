"""RedisBus against a throwaway redis-server. Skipped when redis-server isn't installed."""

import shutil
import socket
import subprocess
import time

import pytest

from protocol import Envelope, Identity
from protocol.contract import Bid
from substrate.bus import BadSignature, RedisBus
from substrate.registry import Registry

pytestmark = pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server not installed")


@pytest.fixture
def redis_url(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--save", "", "--appendonly", "no", "--dir", str(tmp_path)],
        stdout=subprocess.DEVNULL,
    )
    deadline = time.time() + 15  # generous: under a busy suite redis-server can take several seconds to start
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            if time.time() > deadline:
                proc.terminate()
                pytest.fail(f"redis-server didn't start on port {port} within 15 s")
            time.sleep(0.05)
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait()


def test_redis_bus_streams_and_groups(redis_url):
    reg = Registry()
    a = Identity("a")
    reg.register("a", a.public, ["build"])
    bus = RedisBus(reg, url=redis_url, base_allowance=10)

    ids = [bus.publish(Envelope.seal(a, Bid(job_id=f"j{i}", price=i + 1), 0)) for i in range(3)]
    got = bus.read("contract", "coop-b")
    assert [e.id for e in got] == ids
    assert got[0].verify(a.public)
    assert bus.read("contract", "coop-b") == []  # acked
    assert len(bus.read("contract", "coop-c")) == 3  # separate group, full replay
    assert bus.r.xlen("commons:contract") == 3

    with pytest.raises(BadSignature):
        bus.publish(Envelope.seal(Identity("a"), Bid(job_id="x", price=1), 0))
