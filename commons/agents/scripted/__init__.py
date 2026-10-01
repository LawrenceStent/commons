from commons.agents.scripted.base import Strategy, quality_of
from commons.agents.scripted.scripted import Cooperator, Defector, FreeRider

# the scripted kinds a society's blueprints may name (application/founding.py)
SCRIPTED = {"cooperator": Cooperator, "defector": Defector, "free-rider": FreeRider}

__all__ = ["Strategy", "quality_of", "Cooperator", "Defector", "FreeRider", "SCRIPTED"]
