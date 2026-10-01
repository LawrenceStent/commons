import pytest

from protocol import Envelope, Identity
from protocol.contract import Announce, Bid, Deliver
from protocol.reputation import Attest, Gossip
from substrate.bus import BadSignature, MemoryBus, RateLimited, allowance_for
from substrate.ledger import InsufficientFunds, Ledger, purse
from substrate.meter import KillSwitch, Meter, Usage, cost_micros
from substrate.registry import Registry
from substrate.reputation import Reputation
from substrate.workspace import Workspace, WorkspaceEscape


# ── protocol ──────────────────────────────────────────────────
def test_envelope_roundtrip_and_tamper():
    a = Identity("a")
    env = Envelope.seal(a, Bid(job_id="j1", price=10), cycle=3)
    assert env.verify(a.public)
    assert env.open() == Bid(job_id="j1", price=10)

    forged = env.model_copy(update={"body": {"job_id": "j1", "price": 1}})
    assert not forged.verify(a.public)
    assert not env.verify(Identity("a").public)  # same name, different key


def test_messages_reject_bad_fields():
    with pytest.raises(Exception):
        Bid(job_id="j", price=0)
    with pytest.raises(Exception):
        Attest(job_id="j", subject="x", capability="c", outcome=1.5)


# ── ledger ────────────────────────────────────────────────────
def test_ledger_balances_and_refuses_overdraft():
    led = Ledger()
    led.transfer("genesis", purse("a"), 100, cycle=0, kind="genesis")
    led.transfer(purse("a"), purse("b"), 60, cycle=1, kind="contract")
    assert led.balance(purse("a")) == 40 and led.balance(purse("b")) == 60
    with pytest.raises(InsufficientFunds):
        led.transfer(purse("a"), purse("b"), 41, cycle=1, kind="contract")
    assert led.balance(purse("a")) == 40  # failed transfer left no trace
    with pytest.raises(ValueError):
        led.post([(purse("a"), -1)], cycle=1, kind="x")
    led.check()


def test_revenue_split_70_20_10():
    led = Ledger()
    led.settle_revenue("a", 1000, cycle=1)
    assert led.balance(purse("a")) == 700
    assert led.balance("treasury") == 300  # no citations: royalty slice goes to treasury

    led.settle_revenue("a", 1000, cycle=2, royalties={"b": 3, "c": 1})
    assert led.balance(purse("b")) == 75 and led.balance(purse("c")) == 25
    assert led.balance("treasury") == 500
    assert led.total() == 0  # market is -2000
    led.check()


def test_ledger_persists_to_disk(tmp_path):
    db = tmp_path / "ledger.db"
    led = Ledger(str(db))
    led.transfer("genesis", purse("a"), 5, cycle=0, kind="genesis")
    assert Ledger(str(db)).balance(purse("a")) == 5


# ── meter ─────────────────────────────────────────────────────
def test_cost_micros_uses_list_prices():
    # 1M input tokens of Sonnet 5 at $2/Mtok == 2,000,000 micro-dollars
    assert cost_micros("claude-sonnet-5", Usage(input_tokens=1_000_000)) == 2_000_000
    u = Usage(input_tokens=4000, output_tokens=1500, cache_read_input_tokens=8000)
    assert cost_micros("claude-haiku-4-5", u) == 4000 + 7500 + 800


def test_meter_charges_and_the_kill_switch():
    led = Ledger()
    led.transfer("genesis", purse("a"), 1000, cycle=0, kind="genesis")
    m = Meter(led, daily_ceiling=10_000)
    m.charge("a", 80, cycle=1)
    with pytest.raises(InsufficientFunds):
        m.charge("a", 2000, cycle=2)
    m2 = Meter(led, daily_ceiling=100)
    m2.charge("a", 90, cycle=1)
    with pytest.raises(KillSwitch):
        m2.charge("a", 20, cycle=1)
    with pytest.raises(KillSwitch):
        m2.charge("a", 1, cycle=2)  # stays halted until a human resets it
    m2.reset()
    m2.charge("a", 1, cycle=2)


# ── reputation ────────────────────────────────────────────────
def test_reputation_direct_scoped_and_decaying():
    r = Reputation(decay=0.9)
    assert r.score("a", "x", "build") == 0.5
    for _ in range(5):
        r.attest("a", "x", "build", 0.0)
    assert r.score("a", "x", "build") < 0.2
    assert r.score("a", "x", "design") == 0.5  # scoped by capability
    r.attest("x", "x", "build", 1.0)  # self-attestation is ignored
    assert r.standing("x") < 0.2
    low = r.score("a", "x", "build")
    for _ in range(50):
        r.tick()
    assert low < r.score("a", "x", "build") < 0.5  # forgiveness, not amnesia at once


def test_gossip_is_discounted_by_trust_in_source_and_does_not_compound():
    r = Reputation()
    for _ in range(10):
        r.attest("b", "x", "build", 0.0)  # b knows x is bad
        r.attest("a", "b", "build", 1.0)  # a trusts b
        r.attest("a", "m", "build", 0.0)  # a distrusts m
    r.hear("a", "b", "x", "build", score=0.0, evidence=10)
    trusted = r.score("a", "x", "build")
    assert trusted < 0.35

    r2 = Reputation()
    for _ in range(10):
        r2.attest("a", "m", "build", 0.0)
    r2.hear("a", "m", "x", "build", score=0.0, evidence=10)
    assert r2.score("a", "x", "build") > trusted  # a liar's gossip moves you less

    for _ in range(20):
        r.hear("a", "b", "x", "build", score=0.0, evidence=10)
    assert r.score("a", "x", "build") == pytest.approx(trusted)  # repeats replace, not add


# ── bus ───────────────────────────────────────────────────────
def _bus(standing=0.5, base=3):
    reg = Registry()
    a, b = Identity("a"), Identity("b")
    reg.register("a", a.public, ["build"])
    reg.register("b", b.public, ["design"])
    return MemoryBus(reg, standing=lambda _: standing, base_allowance=base), a, b


def test_bus_rejects_unsigned_and_unregistered():
    bus, a, _ = _bus()
    stranger = Identity("a")  # claims a's name with a different key
    with pytest.raises(BadSignature):
        bus.publish(Envelope.seal(stranger, Bid(job_id="j", price=1), 0))
    with pytest.raises(BadSignature):
        bus.publish(Envelope.seal(Identity("zed"), Bid(job_id="j", price=1), 0))


def test_bus_rate_limit_and_exemptions():
    bus, a, _ = _bus(base=2)
    bus.begin_cycle(1)
    for i in range(2):
        bus.publish(Envelope.seal(a, Bid(job_id=f"j{i}", price=1), 1))
    with pytest.raises(RateLimited):
        bus.publish(Envelope.seal(a, Bid(job_id="j9", price=1), 1))
    # obligations still go through when over the limit
    bus.publish(Envelope.seal(a, Deliver(job_id="j0", artifact={}), 1))
    bus.publish(Envelope.seal(a, Attest(job_id="j0", subject="b", capability="build", outcome=1), 1))
    bus.begin_cycle(2)
    bus.publish(Envelope.seal(a, Bid(job_id="j10", price=1), 2))


def test_allowance_scales_with_standing():
    assert allowance_for(0.5, 12) == 12
    assert allowance_for(0.9, 12) == 18
    assert allowance_for(0.25, 12) == 4
    assert allowance_for(0.0, 12) == 1
    assert [allowance_for(s / 10, 12) for s in range(11)] == sorted(allowance_for(s / 10, 12) for s in range(11))


def test_memory_bus_consumer_groups_are_independent():
    bus, a, b = _bus(base=10)
    bus.publish(Envelope.seal(a, Announce(job_id="j", capability="c", reward=5, advance_frac=0.5), 0))
    bus.publish(Envelope.seal(b, Gossip(subject="a", capability="c", score=0.9, evidence=1), 0))
    assert [e.verb for e in bus.read("contract", "g1")] == ["announce"]
    assert bus.read("contract", "g1") == []
    assert len(bus.read("contract", "g2")) == 1
    assert len(bus.read("reputation", "g1")) == 1


# ── workspace ─────────────────────────────────────────────────
def test_workspace_isolation(tmp_path):
    ws = Workspace(tmp_path, "coop-a")
    ws.write("notes/a.md", "hi")
    assert ws.read("notes/a.md") == "hi"
    for bad in ("../coop-b/x", "/etc/passwd", "notes/../../x"):
        with pytest.raises(WorkspaceEscape):
            ws.path(bad)


def test_memory_bus_backlog_is_capped_even_with_no_readers():
    from protocol import Envelope, Identity
    from protocol.knowledge import Publish
    from substrate.bus import MemoryBus
    from substrate.registry import Registry

    me = Identity("a")
    reg = Registry()
    reg.register("a", me.public, ["write"])
    bus = MemoryBus(reg, base_allowance=10**6, max_backlog=50)
    for i in range(500):
        bus.publish(Envelope.seal(me, Publish(playbook_id=str(i), capability="write", title="t", content_hash="h"), 0))
        bus.compact()
    assert len(bus._streams["knowledge"]) == 50
    assert [e.open().playbook_id for e in bus.read("knowledge", "late")][0] == "450"
