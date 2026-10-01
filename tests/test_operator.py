"""The operator: directives and context reach the stewards; limits are enforced by the world."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from commons.agents.llm.render import operator_block
from commons.application.actions import Actions
from commons.application.operator import Operator
from commons.application.world import Params, World, default_population
from commons.domain.community import Community

EXAMPLE = Path(__file__).parent.parent / "operator.example"


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "operator"
    shutil.copytree(EXAMPLE, d)
    return d


def test_the_example_folder_loads_and_merges_all_with_each_coop(folder):
    op = Operator(folder)
    assert op.errors == []
    studio, lab, other = op.view("studio"), op.view("lab"), op.view("nobody")
    assert "Aim for work" in studio.directives and "students" in studio.directives
    assert "students" not in lab.directives and "Aim for work" in lab.directives
    assert studio.context[0][0] == "context/house-style.md"
    assert studio.limits.forbid == {"propose_merge", "accept_merge"} and studio.limits.max_price == 200000
    assert lab.runtime == {"max_rounds": 6} and lab.limits.max_price is None
    assert other.directives == op.all.directives  # co-ops without their own file get the shared directives


def test_a_coop_limit_can_only_tighten_the_shared_one(folder):
    (folder / "config.toml").write_text('[all.limits]\nmax_price = 100000\n[coops.studio.limits]\nmax_price = 300000\n')
    assert Operator(folder).view("studio").limits.max_price == 100000


def test_limits_are_world_rules_for_every_kind_of_agent(folder):
    w = World(Params(seed=0, verify=False), operator=Operator(folder))
    w.step()
    coop_a = Actions(w, w.communities["coop-a"])  # a scripted co-op: limits apply to it too
    assert "doesn't allow propose merge" in coop_a.propose_merge("coop-b").message
    studio = Community("studio", 2, {"write"}, default_population()[0].strategy)
    w.add_community(studio)
    act = Actions(w, studio)
    studio.capacity = 5
    contract = next((c for c in w.contracts.values() if c.status == "open"), None)
    out = act.bid(contract.id if contract else "none", 250_000)
    assert "caps bids and announcements at 200000" in out.message


def test_a_broken_config_keeps_the_last_good_one_and_says_why(folder):
    op = Operator(folder)
    (folder / "config.toml").write_text("[all.limits]\nmax_speed = 3\n")
    assert op.reload() and "unknown limits" in op.errors[0]
    assert op.view("studio").limits.max_price == 200000  # the last good version still applies


def test_changes_are_picked_up_each_cycle_and_logged(folder):
    w = World(Params(seed=0, verify=False), operator=Operator(folder))
    w.step()
    (folder / "coops" / "lab.md").write_text("Only take research work this week.")
    w.step()
    assert "research work this week" in w.operator.view("lab").directives
    assert any(e.name == "operator.update" for e in w.activity.ring)


def test_the_steward_sees_directives_limits_and_context_as_trusted_instructions(folder):
    from commons.adapters.models import FakeBackend
    from commons.agents.llm.fakes import GOOD_GRADE, competent
    from commons.agents.llm.steward import LLMStrategy

    backend = FakeBackend(respond=lambda *a: GOOD_GRADE, converse=competent)
    pop = [Community("studio", 3, {"write", "design"}, LLMStrategy(backend))] + default_population()[:2]
    w = World(Params(seed=0, verify=False), population=pop, operator=Operator(folder))
    w.step()
    system = next(c[0] for c in backend.chats if c[2] is not None)
    assert len(system) == 4 and system[1].startswith("WHAT THIS SOCIETY IS FOR") and system[3].startswith("FROM YOUR OPERATOR")
    assert "students" in system[3] and "House style" in system[3] and "No bid or announcement above 200000" in system[3]
    assert operator_block(Operator(None).view("studio")) is None  # no folder, no block


def test_the_thinking_budget_ends_a_turn(folder):
    from commons.adapters.models import FakeBackend
    from commons.agents.llm.steward import LLMStrategy

    (folder / "config.toml").write_text("[coops.studio.limits]\nthinking_budget = 1\n")
    backend = FakeBackend(converse=lambda s, m, t: {"tool_calls": [("note", {"text": "hm"})]} if t else {"text": "x"})
    pop = [Community("studio", 3, {"write"}, LLMStrategy(backend))] + default_population()[:1]
    w = World(Params(seed=0, verify=False), population=pop, operator=Operator(folder))
    w.step()
    assert len([c for c in backend.chats if c[2] is not None]) == 1
    assert any("thinking budget" in e.get("text", "") for e in w.transcripts["studio"][-1]["entries"])


def test_directives_can_be_edited_from_the_dashboard(folder):
    from commons.interfaces.console.app import create_app

    w = World(Params(seed=0, verify=False), operator=Operator(folder))
    with TestClient(create_app(w, autostart=False)) as client:
        snap = client.get("/api/snapshot").json()["operator"]
        assert snap["enabled"] and "Aim for work" in snap["all"]
        assert client.post("/api/operator", json={"coop": "coop-a", "directives": "Be bold."}).json()["ok"]
        assert "Be bold." in w.operator.view("coop-a").directives
        assert client.post("/api/operator", json={"coop": "nobody", "directives": "x"}).status_code == 404
        assert (folder / "coops" / "coop-a.md").read_text() == "Be bold."


def test_context_files_must_stay_inside_the_folder(folder):
    (folder / "config.toml").write_text('[all]\ncontext = ["../../etc/passwd"]\n')
    assert "outside the operator folder" in Operator(folder).errors[0]


def test_an_unknown_forbidden_action_is_an_error_not_a_silent_allow(folder):
    (folder / "config.toml").write_text('[all.limits]\nforbid = ["mergee"]\n')
    assert "unknown action 'mergee'" in Operator(folder).errors[0]
