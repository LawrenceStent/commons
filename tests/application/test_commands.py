"""R8: the executor, by area. Every role an agent may depend on is implemented, and every command declares its
pipeline where it is defined (no wrapping at import)."""

import inspect

from commons.application import observation
from commons.application.actions import Actions
from commons.application.commands import desk, knowledge, market, planning, population


def _members(protocol):
    """Its methods, its bases' included (a Protocol's own `vars` hold only what it declares itself)."""
    return {n for k in protocol.__mro__ if k.__module__ == observation.__name__
            for n, v in vars(k).items() if callable(v) and not n.startswith("_")}


def test_the_executor_implements_every_role():
    roles = (observation.MarketActions, observation.PopulationActions, observation.KnowledgeActions,
             observation.PlanningActions, observation.DeskActions)
    for role in roles:
        missing = _members(role) - set(dir(Actions))
        assert not missing, f"{role.__name__}: {missing}"
    assert _members(observation.ActionsAPI) == set().union(*(_members(r) for r in roles))


def test_each_area_implements_its_role():
    pairs = [(market.MarketCommands, observation.MarketActions), (population.PopulationCommands, observation.PopulationActions),
             (knowledge.KnowledgeCommands, observation.KnowledgeActions), (desk.DeskCommands, observation.DeskActions)]
    for cls, role in pairs:
        assert _members(role) <= set(vars(cls)), cls.__name__
    assert _members(observation.PlanningActions) - {"spend"} <= set(vars(planning.PlanningCommands))


def test_no_wrapping_happens_at_import():
    import commons.application.actions as actions

    assert "setattr" not in inspect.getsource(actions)


def test_both_kinds_of_agent_meet_the_agent_interface_and_the_llm_one_stands_alone():
    from commons.agents.llm.steward import LLMStrategy
    from commons.agents.scripted import Cooperator
    from commons.domain.community import Agent

    agent_members = {n for n in vars(Agent) if not n.startswith("_")} | set(Agent.__annotations__)
    for cls in (LLMStrategy, Cooperator):
        missing = {m for m in agent_members if not hasattr(cls, m) and m != "rng"}
        assert not missing, (cls.__name__, missing)
    assert LLMStrategy.__mro__[1] is object  # it inherits none of the scripted hooks
