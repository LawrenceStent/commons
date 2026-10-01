"""Ideas and goals: what a community means to do, written down so it can be seen and tracked.

Stewards record ideas as they have them and turn some into goals with a checklist of steps, then tick
steps off turn by turn. Both are shown back to the community in its observation (a memory that
outlasts one conversation) and on the dashboard (so you can see what each co-op is working towards,
and how far it has got).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from commons.domain.status import GoalStatus, IdeaStatus

MAX_ACTIVE_GOALS = 8
MAX_STEPS = 12
KEEP_IDEAS = 30
KEEP_CLOSED_GOALS = 10


@dataclass
class Step:
    text: str
    done: bool = False
    note: str = ""


@dataclass
class Goal:
    id: str
    title: str
    steps: list[Step]
    created: int
    updated: int
    status: GoalStatus = GoalStatus.ACTIVE
    idea_id: str | None = None
    outcome: str = ""

    @property
    def progress(self) -> float:
        return sum(s.done for s in self.steps) / len(self.steps) if self.steps else (1.0 if self.status == GoalStatus.DONE else 0.0)


@dataclass
class Idea:
    id: str
    title: str
    detail: str
    cycle: int
    status: IdeaStatus = IdeaStatus.NEW
    goal_id: str | None = None


@dataclass
class Plans:
    """One community's ideas and goals."""
    ideas: list[Idea] = field(default_factory=list)
    goals: dict[str, Goal] = field(default_factory=dict)

    def active(self) -> list[Goal]:
        return [g for g in self.goals.values() if g.status == GoalStatus.ACTIVE]

    def trim(self) -> None:
        del self.ideas[:-KEEP_IDEAS]
        closed = [g for g in self.goals.values() if g.status != GoalStatus.ACTIVE]
        for g in sorted(closed, key=lambda g: g.updated)[:-KEEP_CLOSED_GOALS]:
            del self.goals[g.id]
