"""R8: the executor, by area. Every role an agent may depend on is implemented, and every command declares its
pipeline where it is defined (no wrapping at import)."""

import inspect

from commons.application import observation
from commons.application.actions import Actions
from commons.application.commands import knowledge, market, planning, population


def _members(protocol):
    """Its methods, its bases' included (a Protocol's own `vars` hold only what it declares itself)."""
    return {n for k in protocol.__mro__ if k.__module__ == observation.__name__
            for n, v in vars(k).items() if callable(v) and not n.startswith("_")}


def test_the_executor_implements_every_role():
    roles = (observation.MarketActions, observation.PopulationActions, observation.KnowledgeActions,
             observation.PlanningActions)
    for role in roles:
        missing = _members(role) - set(dir(Actions))
        assert not missing, f"{role.__name__}: {missing}"
    assert _members(observation.ActionsAPI) == set().union(*(_members(r) for r in roles))


def test_each_area_implements_its_role():
    pairs = [(market.MarketCommands, observation.MarketActions), (population.PopulationCommands, observation.PopulationActions),
             (knowledge.KnowledgeCommands, observation.KnowledgeActions)]
    for cls, role in pairs:
        assert _members(role) <= set(vars(cls)), cls.__name__
    assert _members(observation.PlanningActions) - {"spend"} <= set(vars(planning.PlanningCommands))


def test_no_wrapping_happens_at_import():
    import commons.application.actions as actions

    assert "setattr" not in inspect.getsource(actions)
