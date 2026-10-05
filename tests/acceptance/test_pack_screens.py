"""K7.1: a pack's screen (Pack.screen) is a rule over what enters its society: briefs and questions at founding, web
requests before the gate, work at hand-in. A refusal is a screened attempt: logged, the co-op told, and with
Pack.halt_on_screen the society halts until you reset it. A toy screen, defined here, on the unchanged kernel."""

from dataclasses import replace

import pytest

from commons.application import founding
from commons.application.actions import Actions
from commons.application.society import Params, World
from commons.domain.founding import FoundingError
from commons.domain.market import MarketJob, Part
from commons.domain.pack import load


def no_secrets(kind, text):
    return "that mentions a secret" if "secret" in text.lower() else None


def society(halt=False, **kw):
    pack = replace(load(), screen=no_secrets, halt_on_screen=halt)
    return World(Params(seed=0, verify=False, claim_allocation=False, **kw), pack=pack).run(1)


def claimed(w):
    me = w.communities["coop-a"]
    me.capacity = 5  # room to act in these tests
    cap = sorted(me.capabilities)[0]
    job = MarketJob("T1", "t", 80_000, {cap: Part(cap, "s", "r")}, posted=w.cycle, deadline=w.cycle + 3)
    w.jobs[job.id] = job
    assert Actions(w, me).claim(job.id)
    return Actions(w, me), job, cap


def test_work_that_fails_the_screen_is_refused_at_hand_in_and_logged():
    w = society()
    act, job, cap = claimed(w)
    out = act.do_part(job.id, cap, "here is the secret plan")
    assert not out and "screen" in out.message and "secret" in out.message
    assert job.parts[cap].artifact is None
    assert [e.fields["kind"] for e in w.hub.recent("pack.screened")] == ["work"]
    assert act.do_part(job.id, cap, "an ordinary plan")
    assert not w.meter.halted


def test_a_halting_screen_stops_the_society_until_reset():
    w = society(halt=True)
    act, job, cap = claimed(w)
    act.do_part(job.id, cap, "a secret")
    assert w.meter.halted


def test_web_requests_are_screened_before_the_gate():
    from commons.domain.gate import GatePolicy

    w = society()
    w.web = object()  # a web that must never be touched: the screen refuses first
    w.gate.policy = GatePolicy(read="allow", allow_hosts=("en.wikipedia.org",))
    out = Actions(w, w.communities["coop-a"]).web_search("where the secret is kept")
    assert not out and "secret" in out.message and w.gate.requests == {}


def test_founding_screens_the_brief_and_questions(tmp_path, monkeypatch):
    import commons.domain.pack as packs

    real = packs.load
    monkeypatch.setattr(founding, "load_pack", lambda name=None: replace(real(name), screen=no_secrets))
    with pytest.raises(FoundingError, match="secret"):
        founding.found("toy", None, "Find the secret.", None, 3, backend=None, model="m", root=tmp_path)
    with pytest.raises(FoundingError, match="secret"):
        founding.found("toy", None, "A fine brief.", None, 3, backend=None, model="m", root=tmp_path,
                       questions="ordinary question\nthe secret one")
    assert not (tmp_path / "toy").exists()  # refused before any model call or file
