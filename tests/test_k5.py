"""K5: members use tools, and the gate holds. Done when a gated tool can't run without approval, proven here.

Two enforcement points, tested separately: the gate in the tool layer (sim/gate.py) and the egress allowlist in the
network layer (runtime/web.py). No test touches the network: a fake transport records every request.
"""

import json

import pytest
from fastapi.testclient import TestClient

from commons.adapters.models import FakeBackend
from commons.adapters.web import Egress, EgressDenied, Fetcher, WebAccess, WebError, WikipediaSearch, html_to_text
from commons.agents.llm.steward import LLMStrategy
from commons.agents.llm.tools import OFFLINE, TOOLS
from commons.agents.scripted import Cooperator
from commons.application.actions import Actions
from commons.application.gate import Gate, pending_in, record
from commons.application.operator import Operator
from commons.application.world import Params, World
from commons.domain.community import Community
from commons.domain.gate import GateError, GatePolicy
from commons.domain.market import MarketJob, Part
from commons.interfaces.console.app import create_app

PAGE = b"<html><head><title>Hand pumps</title><script>track()</script></head><body><nav>menu</nav>" \
       b"<p>Hand pumps fail most often because spare parts are hard to find.</p><p>Village committees help.</p></body></html>"


class FakeTransport:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls: list[str] = []

    def __call__(self, url, headers):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return self.pages.get(url, (404, {}, b""))
        return self.pages.get(url, (200, {"content-type": "text/html"}, PAGE))


def web(transport, private=()):
    return WebAccess(Fetcher(Egress((), resolve=lambda h: h in private), transport=transport),
                     WikipediaSearch.__new__(WikipediaSearch))  # replaced below where a test searches


def world(tmp_path, gate="read = \"ask\"\nallow_hosts = [\"example.org\", \"*.wiki.example\"]", transport=None, **kw):
    (tmp_path / "op").mkdir(exist_ok=True)
    (tmp_path / "op" / "config.toml").write_text(f"[gate]\n{gate}\n")
    t = transport or FakeTransport()
    gate_obj = kw.pop("gate_obj", None)
    w = World(Params(seed=0, verify=False, **kw), operator=Operator(tmp_path / "op"), web=web(t), gate=gate_obj)
    return w, t


def told(w):
    """Record what the world tells co-ops (their inboxes are cleared after every turn)."""
    out = []
    real = w._tell
    w._tell = lambda name, kind, text, ref=None: (out.append((name, text)), real(name, kind, text, ref))
    return out


def act(w, name="coop-a"):
    a = Actions(w, w.communities[name])
    a.actor = "steward"
    return a


# ── the done-when: nothing runs without approval ───────────────
def test_a_gated_read_never_reaches_the_network_without_approval(tmp_path):
    w, net = world(tmp_path)
    said = told(w)
    w.step()
    out = act(w).web_fetch("https://example.org/pumps")
    assert not out and "waiting for the operator's approval as G1" in out.message
    assert net.calls == []
    again = act(w).web_fetch("https://example.org/pumps")
    assert "G1" in again.message and len(w.gate.requests) == 1  # asking twice doesn't queue twice
    for _ in range(3):
        w.step()
    assert net.calls == [], "no decision, no request"
    w.gate_decide(["G1"], approve=False, reason="not now")
    w.step()
    assert net.calls == [] and w.gate.requests["G1"].status == "denied"
    assert ("coop-a", "the operator denied G1 (web_fetch https://example.org/pumps): not now") in said


def test_an_approved_read_runs_next_cycle_joins_the_archive_and_can_be_cited(tmp_path):
    w, net = world(tmp_path)
    said = told(w)
    w.step()
    act(w).web_fetch("https://example.org/pumps")
    w.gate_decide(["G1"], approve=True)
    assert net.calls == []  # approval alone sends nothing; the world runs it at the start of the next cycle
    w.step()
    assert net.calls == ["https://example.org/robots.txt", "https://example.org/pumps"]
    ids = w.web_pages["https://example.org/pumps"]
    assert ids == ["web-example-org-pumps#1"] and "spare parts are hard to find" in w.archive.get(ids[0]).text
    assert "track()" not in w.archive.get(ids[0]).text and "menu" not in w.archive.get(ids[0]).text
    assert any(n == "coop-a" and text.startswith("G1 ran: read https://example.org/pumps") for n, text in said)
    assert w._try_grade("s", "r", f"<q=0.9> pumps [archive: {ids[0]}]").score == pytest.approx(0.9)
    assert w._try_grade("s", "r", "<q=0.9> [archive: web-example-org-invented#1]").score == 0  # a page no one read
    again = act(w).web_fetch("https://example.org/pumps")
    assert again and "already read" in again.message and len(net.calls) == 2  # read once


def test_expired_requests_never_run(tmp_path):
    w, net = world(tmp_path, gate='read = "ask"\nallow_hosts = ["example.org"]\nttl = 2')
    w.step()
    act(w).web_fetch("https://example.org/a")
    w.run(3)
    assert w.gate.requests["G1"].status == "expired" and net.calls == []
    assert not w.gate_decide(["G1"], approve=True)  # too late


# ── policies ───────────────────────────────────────────────────
def test_allow_runs_reads_at_once_but_only_on_the_allowlist(tmp_path):
    w, net = world(tmp_path, gate='read = "allow"\nallow_hosts = ["example.org"]')
    w.step()
    assert act(w).web_fetch("https://example.org/a")
    assert len(net.calls) == 2
    off = act(w).web_fetch("https://elsewhere.net/a")
    assert not off and "not on the operator's allowlist" in off.message and len(net.calls) == 2


def test_always_approves_that_coop_and_host_only(tmp_path):
    w, net = world(tmp_path)
    w.step()
    act(w).web_fetch("https://example.org/a")
    w.gate_decide(["G1"], approve=True, always=True)
    w.step()
    assert act(w).web_fetch("https://example.org/b"), "standing approval: runs at once"
    assert not act(w, "coop-b").web_fetch("https://example.org/c"), "another co-op still asks"
    w.gate.revoke("coop-a", "example.org")
    assert not act(w).web_fetch("https://example.org/d")


def test_deny_and_the_operator_forbid_list(tmp_path):
    w, net = world(tmp_path, gate='read = "deny"\nallow_hosts = ["example.org"]')
    w.step()
    assert "doesn't allow read tools" in act(w).web_fetch("https://example.org/a").message
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "allow"\nallow_hosts = ["example.org"]\n'
                                                 '[all.limits]\nforbid = ["web"]\n')
    w.step()
    assert "doesn't allow web fetch" in act(w).web_fetch("https://example.org/a").message
    assert net.calls == []


def test_the_policy_is_strict():
    with pytest.raises(GateError, match="always needs you"):
        GatePolicy.parse({"publish": "allow"})
    with pytest.raises(GateError, match="unknown"):
        GatePolicy.parse({"reads": "allow"})
    with pytest.raises(GateError):
        GatePolicy.parse({"read": "sometimes"})
    assert GatePolicy.parse({"allow_hosts": ["*.Example.org"]}).allows_host("docs.example.org")


def test_a_broken_gate_config_keeps_the_last_good_one(tmp_path):
    w, _ = world(tmp_path)
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "allow"\npublish = "allow"\nallow_hosts = ["x.org"]\n')
    w.step()
    assert w.gate.policy.read == "ask" and "always needs you" in w.operator.errors[0]


def test_web_calls_per_cycle_are_a_rule(tmp_path):
    w, net = world(tmp_path, gate='read = "allow"\nallow_hosts = ["example.org"]\nper_cycle = 2')
    w.step()
    assert act(w).web_fetch("https://example.org/1") and act(w).web_fetch("https://example.org/2")
    assert "used your 2 web calls" in act(w).web_fetch("https://example.org/3").message
    w.step()
    assert act(w).web_fetch("https://example.org/3")


def test_no_hosts_means_no_web(tmp_path):
    w = World(Params(seed=0, verify=False))
    w.step()
    assert "no web access" in act(w).web_fetch("https://example.org/").message
    assert w.observe(w.communities["coop-a"]).web == ""
    w2, _ = world(tmp_path)
    assert "WEB:" in w2.observe(w2.communities["coop-a"]).web and "each read waits" in w2.observe(w2.communities["coop-a"]).web


# ── the second enforcement point: the network layer on its own ─
@pytest.mark.parametrize("url, why", [
    ("http://example.org/", "only https"),
    ("https://93.184.216.34/", "host names, not IPs"),
    ("https://elsewhere.net/", "not on the operator's allowlist"),
    ("https://user:pw@example.org/", "credentials"),
    ("https://internal.example.org/", "private address"),
])
def test_egress_refuses_before_sending_anything(url, why):
    net = FakeTransport()
    f = Fetcher(Egress(["example.org", "*.example.org"], resolve=lambda h: h == "internal.example.org"), transport=net)
    with pytest.raises(EgressDenied, match=why):
        f.fetch(url)
    assert net.calls == []


def test_a_redirect_off_the_allowlist_is_refused():
    net = FakeTransport({"https://example.org/go": (302, {"location": "https://evil.net/x"}, b"")})
    f = Fetcher(Egress(["example.org"], resolve=lambda h: False), transport=net)
    with pytest.raises(EgressDenied, match="evil.net"):
        f.fetch("https://example.org/go")
    assert "https://evil.net/x" not in net.calls


def test_the_network_layer_holds_even_if_the_gate_approved(tmp_path):
    """An approval for a host the operator has since removed from the allowlist still can't reach it."""
    w, net = world(tmp_path)
    w.step()
    act(w).web_fetch("https://example.org/a")
    w.gate_decide(["G1"], approve=True)
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "ask"\nallow_hosts = ["other.org"]\n')
    w.step()
    assert net.calls == [] and w.gate.requests["G1"].status == "failed"
    assert "not on the operator's allowlist" in w.gate.requests["G1"].result


def test_robots_and_content_rules():
    net = FakeTransport({"https://example.org/robots.txt": (200, {}, b"User-agent: *\nDisallow: /private\n"),
                         "https://example.org/pic": (200, {"content-type": "image/png"}, b"\x89PNG")})
    f = Fetcher(Egress(["example.org"], resolve=lambda h: False), transport=net)
    with pytest.raises(WebError, match="robots.txt"):
        f.fetch("https://example.org/private/page")
    assert "https://example.org/private/page" not in net.calls
    with pytest.raises(WebError, match="not text"):
        f.fetch("https://example.org/pic")
    big = FakeTransport({"https://example.org/big": (200, {"content-type": "text/plain"}, b"x" * 3000)})
    with pytest.raises(WebError, match="larger than"):
        Fetcher(Egress(["example.org"], resolve=lambda h: False), transport=big, max_bytes=2000).fetch("https://example.org/big")


def test_html_becomes_plain_text():
    title, text = html_to_text(PAGE.decode())
    assert title == "Hand pumps" and "spare parts" in text and "track()" not in text and "menu" not in text


def test_search_goes_through_the_same_allowlist(tmp_path):
    api = {"query": {"search": [{"title": "Hand pump", "snippet": "a <span>pump</span> worked by hand"}]}}
    net = FakeTransport({})
    net.pages = {k: v for k, v in net.pages.items()}

    def transport(url, headers):
        net.calls.append(url)
        return 200, {"content-type": "application/json"}, json.dumps(api).encode()

    fetcher = Fetcher(Egress((), resolve=lambda h: False), transport=transport)
    access = WebAccess(fetcher, WikipediaSearch(fetcher))
    (tmp_path / "op").mkdir()
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "allow"\nallow_hosts = ["example.org"]\n')
    w = World(Params(seed=0, verify=False), operator=Operator(tmp_path / "op"), web=access)
    w.step()
    refused = act(w).web_search("hand pumps")
    assert not refused and "en.wikipedia.org is not on" in refused.message and net.calls == []
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "allow"\nallow_hosts = ["en.wikipedia.org"]\n')
    w.step()
    found = act(w).web_search("hand pumps")
    assert found and "Hand pump: https://en.wikipedia.org/wiki/Hand_pump" in found.message and "<span>" not in found.message
    assert net.calls[0].startswith("https://en.wikipedia.org/w/api.php?") and "robots.txt" not in net.calls[0]


# ── members use tools ──────────────────────────────────────────
def test_a_member_looks_things_up_through_the_gate_then_writes(tmp_path):
    (tmp_path / "op").mkdir()
    (tmp_path / "op" / "config.toml").write_text('[gate]\nread = "allow"\nallow_hosts = ["example.org"]\n')
    net = FakeTransport()
    seen = []

    def converse(system, messages, tools):
        if tools and any(t["name"] == "claim" for t in tools):  # the steward: does nothing
            return {"tool_calls": [("end_turn", {})]}
        names = {t["name"] for t in tools or []}
        results = [r for m in messages if m["role"] == "tool" for r in m["results"]]
        seen.append((names, len(results)))
        if not results:
            return {"tool_calls": [("web_fetch", {"url": "https://example.org/pumps"}), ("claim", {"job_id": "X1"})]}
        return {"text": "Spare parts are the problem [archive: web-example-org-pumps#1]."}

    backend = FakeBackend(converse=converse)
    me = Community("fieldwork", 3, {"research", "write"}, LLMStrategy(backend), charter="c")
    w = World(Params(seed=0, verify=False), population=[me, Community("other", 3, {"build"}, Cooperator())],
              operator=Operator(tmp_path / "op"), web=web(net))
    w.step()
    job = MarketJob("X1", "pumps", 80_000, {"research": Part("research", "find out", "three lines")}, posted=w.cycle,
                    deadline=w.cycle + 3)
    w.jobs[job.id] = job
    a = Actions(w, me)
    a.actor = "steward"
    me.capacity = 5
    a.claim(job.id)
    w._allocate_claims()
    me.strategy._commissions = 0
    out = me.strategy.commission(w.observe(me), a, "X1", "research", "go", None)
    assert out and "[archive: web-example-org-pumps#1]" in out.message
    assert seen[0][0] == {"search_archive", "read_archive", "web_search", "web_fetch"}  # no claim, no commission
    tool_msgs = [m for m in backend.chats[-1][1] if m["role"] == "tool"][0]["results"]
    assert tool_msgs[0].content.startswith("read https://example.org/pumps") and "members may only use" in tool_msgs[1].content
    assert any(e.actor == "member" and e.name == "web_fetch" for e in w.activity.recent(50))
    assert w._try_grade("s", "r", "<q=0.8>" + out.message.split("\n", 1)[1]).score == pytest.approx(0.8)


def test_stewards_are_offered_the_web_only_when_there_is_some(tmp_path):
    seen = []
    backend = FakeBackend(converse=lambda s, m, t: seen.append(t) or {"tool_calls": [("end_turn", {})]})
    me = Community("llm", 3, {"research"}, LLMStrategy(backend), charter="c")
    w, _ = world(tmp_path)
    w2 = World(Params(seed=0, verify=False), population=[me], operator=w.operator, web=w.web)
    w2.step()
    assert seen[-1] is TOOLS
    w3 = World(Params(seed=0, verify=False), population=[Community("llm", 3, {"research"}, LLMStrategy(backend), charter="c")])
    w3.step()
    assert seen[-1] is OFFLINE


# ── deciding: files for headless runs, the dashboard for live ones ──
def test_headless_decisions_come_from_the_society_folder(tmp_path):
    folder = tmp_path / "society"
    folder.mkdir()
    w, net = world(tmp_path, gate_obj=Gate(folder=folder, run="r1"))
    w.step()
    act(w).web_fetch("https://example.org/a")
    act(w).web_fetch("https://example.org/b")
    waiting = pending_in(folder)
    assert [r["id"] for r in waiting] == ["r1/G1", "r1/G2"]
    record(folder, "r1/G1", approve=True)
    record(folder, "other-run/G2", approve=True)  # another run's request: ignored
    w.step()  # decisions read, then approved requests run
    assert w.gate.requests["G1"].status == "done" and w.gate.requests["G2"].status == "pending"
    assert [r["id"] for r in pending_in(folder)] == ["r1/G2"]


def test_the_dashboard_decides_in_batches(tmp_path):
    w, net = world(tmp_path)
    w.step()
    act(w).web_fetch("https://example.org/a")
    act(w).web_fetch("https://example.org/b")
    act(w, "coop-b").web_fetch("https://docs.wiki.example/c")
    with TestClient(create_app(w, autostart=False)) as client:
        gate = client.get("/api/snapshot").json()["gate"]
        assert [(g["coop"], len(g["ids"])) for g in gate["groups"]] == [("coop-a", 2), ("coop-b", 1)]
        r = client.post("/api/gate", json={"ids": gate["groups"][0]["ids"], "approve": True, "always": True})
        assert r.json()["decided"] == ["G1", "G2"]
        assert client.get("/api/snapshot").json()["gate"]["standing"] == [["coop-a", "example.org"]]
        client.post("/api/gate", json={"revoke": {"coop": "coop-a", "host": "example.org"}})
        assert client.get("/api/snapshot").json()["gate"]["standing"] == []
    assert net.calls == []
