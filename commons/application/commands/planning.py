"""Planning: ventures, ideas, goals, and the co-op's own notes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commons.application import ventures as ventures_mod
from commons.application.commands.base import MAX_NOTE, CommandBase
from commons.application.commands.pipeline import command
from commons.application.observation import Outcome
from commons.domain.goals import MAX_ACTIVE_GOALS, MAX_STEPS, Goal, Idea, Step
from commons.domain.ids import GoalId, IdeaId
from commons.domain.status import IdeaStatus
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    pass


class PlanningCommands(CommandBase):
    @command()
    def propose_venture(self, title: str, pitch: str, parts: list, idea_id: IdeaId | None = None) -> Outcome:
        """Propose work of your own. Rules refuse at once; the appraisal comes at the start of next cycle."""
        norm = []
        for part in parts or []:
            if isinstance(part, dict):
                norm.append((str(part.get("capability", "")), str(part.get("spec", "")), str(part.get("rubric", ""))))
            elif isinstance(part, (list, tuple)) and len(part) == 3:
                norm.append(tuple(str(x) for x in part))
        title, pitch = str(title)[:120], str(pitch)[:600]
        if why := ventures_mod.check(self.w, self.me, title, pitch, norm):
            return Outcome(False, f"the market won't consider it: {why}")
        if (err := self._use_capacity()) is not None:
            return err
        fee = self.w.params.ventures.venture_fee
        try:
            self.w.ledger.transfer(purse(self.me.name), "treasury", fee, cycle=self.w.cycle, kind="venture", memo=title[:40])
        except InsufficientFunds:
            self.me.capacity += 1
            return Outcome(False, f"proposing a venture costs {fee}; you can't afford it")
        v = ventures_mod.Venture(f"P{self.w.ids.next('venture')}", self.me.name, title, pitch, norm, self.w.cycle, idea_id=idea_id)
        self.w.ventures[v.id] = v
        for i in self.w.plans[self.me.name].ideas:
            if i.id == idea_id:
                i.status = IdeaStatus.ADOPTED
        self.w.hub.emit("venture.proposed", self.w.cycle, id=v.id, proposer=self.me.name, title=title, parts=[c for c, _, _ in norm])
        return Outcome(True, f"venture {v.id} proposed (fee {fee}); it will be appraised at the start of next cycle", v.id)

    @command()
    def idea(self, title: str, detail: str = "") -> Outcome:
        plans = self.w.plans[self.me.name]
        i = Idea(f"I{self.w.ids.next('plan')}", title[:120], detail[:600], self.w.cycle)
        plans.ideas.append(i)
        plans.trim()
        return Outcome(True, f"idea {i.id} recorded", i.id)

    @command()
    def set_goal(self, title: str, steps: list[str], idea_id: IdeaId | None = None) -> Outcome:
        plans = self.w.plans[self.me.name]
        if len(plans.active()) >= MAX_ACTIVE_GOALS:
            return Outcome(False, f"you already have {MAX_ACTIVE_GOALS} active goals; finish or drop one first")
        steps = [str(s)[:200] for s in steps if str(s).strip()][:MAX_STEPS]
        if not steps:
            return Outcome(False, "a goal needs at least one step")
        g = Goal(f"G{self.w.ids.next('plan')}", title[:120], [Step(s) for s in steps], self.w.cycle, self.w.cycle, idea_id=idea_id)
        plans.goals[g.id] = g
        for i in plans.ideas:
            if i.id == idea_id:
                i.status, i.goal_id = IdeaStatus.ADOPTED, g.id
        return Outcome(True, f"goal {g.id} set with {len(steps)} steps", g.id)

    @command()
    def update_goal(self, goal_id: GoalId, step: int | None = None, done: bool | None = None, note: str = "",
                    status: str | None = None) -> Outcome:
        g = self.w.plans[self.me.name].goals.get(goal_id)
        if g is None:
            return Outcome(False, f"no goal {goal_id}")
        if step is not None:
            if not 1 <= int(step) <= len(g.steps):
                return Outcome(False, f"goal {goal_id} has steps 1 to {len(g.steps)}")
            s = g.steps[int(step) - 1]
            if done is not None:
                s.done = bool(done)
            if note:
                s.note = note[:200]
        if status is not None:
            if status not in ("active", "done", "dropped"):
                return Outcome(False, "status is active, done or dropped")
            g.status = status
            g.outcome = note[:300] if note and step is None else g.outcome
        g.updated = self.w.cycle
        self.w.plans[self.me.name].trim()
        return Outcome(True, f"goal {goal_id}: {sum(s.done for s in g.steps)}/{len(g.steps)} steps done, {g.status}")

    @command()
    def note(self, text: str) -> Outcome:
        self.w.journal[self.me.name].append(f"[cycle {self.w.cycle}] {text[:MAX_NOTE]}")
        return Outcome(True, "noted")
