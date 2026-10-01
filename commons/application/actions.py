"""The actions executor: the only way a policy touches the world.

Every call is validated here, costs capacity where it represents work, is signed and published on the bus where the
protocol has a message for it, and moves money only through the ledger. Failures come back as readable Outcomes, never
exceptions, so an LLM can see why something didn't happen and try something else.

The commands live by area in commons/application/commands/ (market, population, knowledge, planning, and the runtime's
own hooks), each declaring what wraps it (commands/pipeline.py). `Actions` is all of them, for one co-op's turn.
"""

from __future__ import annotations

from commons.application.commands.base import MAX_ARTIFACT, MAX_NOTE
from commons.application.commands.knowledge import KnowledgeCommands
from commons.application.commands.market import MarketCommands
from commons.application.commands.planning import PlanningCommands
from commons.application.commands.population import PopulationCommands
from commons.application.commands.runtime import RuntimeHooks

__all__ = ["Actions", "MAX_ARTIFACT", "MAX_NOTE"]


class Actions(MarketCommands, PopulationCommands, KnowledgeCommands, PlanningCommands, RuntimeHooks):
    """Every command a co-op can give, for one turn."""
