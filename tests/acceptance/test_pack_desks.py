"""K6/T2: a pack whose work isn't jobs brings a desk (commons/domain/desk.py): its own tools, a section of each
co-op's view, two phases a cycle and state saved with the society. A toy desk, defined here, runs on the unchanged
kernel: scripted and model-backed co-ops use it, your operator's limits apply to it, and it survives a save."""

from dataclasses import dataclass, field, replace

from commons.adapters.models import FakeBackend
from commons.agents.llm.steward import LLMStrategy
from commons.agents.scripted import Strategy
from commons.application.operator import Operator
from commons.application.society import Params, World
from commons.domain.community import Community
from commons.domain.pack import load

TALLY = {"name": "tally", "description": "Add to your tally. Free.",
         "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"],
                          "additionalProperties": False}}


@dataclass
class TallyDesk:
    tools: tuple = (TALLY,)
    counts: dict = field(default_factory=dict)
    opened: int = 0
    closed: int = 0

    def call(self, world, coop, tool, args):
        if int(args.get("n", 0)) <= 0:
            return False, "n must be positive"
        self.counts[coop] = self.counts.get(coop, 0) + int(args["n"])
        return True, f"tally {self.counts[coop]}"

    def view(self, world, coop):
        return f"Your tally: {self.counts.get(coop, 0)}"

    def open(self, world):
        self.opened += 1

    def close(self, world):
        self.closed += 1


class Counter(Strategy):
    name = "counter"

    def wake(self, obs):
        return 1

    def turn(self, obs, act):
        act.desk_call("tally", {"n": 1})


def toy(population):
    return replace(load(), name="tallies", desk=TallyDesk, population=lambda: population, params={"jobs_per_cycle": 0})


def test_scripted_co_ops_use_the_desk_and_it_runs_each_cycle():
    w = World(Params(seed=0, verify=False, jobs_per_cycle=0),
              pack=toy([Community("a", 2, {"x"}, Counter()), Community("b", 2, {"x"}, Counter())])).run(5)
    assert w.desk.counts == {"a": 5, "b": 5} and w.desk.opened == w.desk.closed == 5
    assert "Your tally: 5" == w.observe(w.communities["a"]).desk
    logged = [e for e in w.activity.recent(100) if e.name == "tally"]
    assert len(logged) == 10 and logged[0].ok and logged[0].args == {"n": 1}


def test_a_model_backed_co_op_gets_the_desk_tools_and_its_view():
    seen = {}

    def steward(system, messages, tools):
        seen["tools"], seen["view"] = [t["name"] for t in tools], messages[0]["text"]
        if len([m for m in messages if m["role"] == "assistant"]) == 0:
            return {"tool_calls": [("tally", {"n": 3}), ("tally", {"n": -1})]}
        return {"tool_calls": [("end_turn", {})]}

    llm = Community("m", 2, {"x"}, LLMStrategy(FakeBackend(converse=steward)))
    w = World(Params(seed=0, verify=False, jobs_per_cycle=0), pack=toy([llm])).run(1)
    assert "tally" in seen["tools"] and seen["tools"] == sorted(seen["tools"])
    assert "YOUR DESK" in seen["view"] and w.desk.counts == {"m": 3}
    assert [e.ok for e in w.activity.recent(10) if e.name == "tally"] == [True, False]


def test_the_operator_can_forbid_a_desk_tool(tmp_path):
    (tmp_path / "config.toml").write_text('[all.limits]\nforbid = ["tally"]\n')
    w = World(Params(seed=0, verify=False, jobs_per_cycle=0), pack=toy([Community("a", 2, {"x"}, Counter())]),
              operator=Operator(tmp_path)).run(2)
    assert w.desk.counts == {}
    assert all(not e.ok for e in w.activity.recent(10) if e.name == "tally")


def test_the_desk_is_saved_with_the_society(tmp_path):
    pack = toy([Community("a", 2, {"x"}, Counter())])
    w = World(Params(seed=0, verify=False, jobs_per_cycle=0, ledger_path=str(tmp_path / "l.sqlite")), pack=pack).run(3)
    w.save(tmp_path / "s.save")
    back = World.resume(tmp_path / "s.save", pack=pack).run(2)  # a pack loads by name; this toy one is passed in
    assert back.desk.counts == {"a": 5} and back.desk.opened == 5
