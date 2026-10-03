"""Grading: submitted jobs, deliveries and audits go to the grader at the end of each cycle.

Model calls run outside the world's lock, up to `grading_workers` at a time; verdicts and money are applied under it, in a
fixed order, so results don't depend on which call finishes first. An unavailable grader is retried next cycle, up to
`grade_retries` times. Before any grading, a rule: work citing archive passages that don't exist fails."""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from commons.application.graders import GradingError
from commons.domain import events as ev
from commons.domain.archive import citations as archive_citations
from commons.domain.grading import Grade
from commons.domain.ids import JobId
from commons.domain.market import MarketJob
from commons.domain.status import (
    ContractStatus,
    JobStatus,
)
from commons.substrate.ledger import InsufficientFunds, purse

if TYPE_CHECKING:
    from commons.application.society import World


class Grading:
    def __init__(self, world: World):
        self.w = world
        self.awaiting_grade = {}  # submitted job id -> failed grading attempts so far
        self.pending_audits = {}  # contract id -> {reason, attempts}
        self.pending_reviews = {}  # delivered contract id -> failed grading attempts
        self.deferred = set()  # graded jobs waiting for their outcome (see Grade.settle_after)
        self.citations = Counter()  # archive citations checked: valid / invalid
        self._cite_lock = threading.Lock()  # grading runs in threads

    def __getstate__(self) -> dict:  # the lock belongs to the process (a saved society: commons/application/saving.py)
        return {k: v for k, v in self.__dict__.items() if k != "_cite_lock"}

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state, _cite_lock=threading.Lock())

    def maybe_submit(self, job: MarketJob) -> None:
        """A complete job is submitted for grading at the end of this cycle. Every part must pass for the
        market to pay."""
        if not job.complete or job.status != JobStatus.CLAIMED or job.id in self.awaiting_grade:
            return
        self.awaiting_grade[job.id] = 0
        self.w.events.publish(ev.JobSubmitted(job))

    def settle(self) -> None:
        """Grade every submitted job and every filed audit. Model calls run outside the world's lock;
        verdicts and money are applied under it. An unavailable grader is retried next cycle, up to
        `grade_retries` times."""
        with self.w.lock:
            jobs = []
            for jid in list(self.awaiting_grade):
                job = self.w.jobs.get(jid)
                if job is None or job.status != JobStatus.CLAIMED:
                    self.awaiting_grade.pop(jid, None)
                    continue
                jobs.append((jid, [(cap, p.spec, p.rubric, p.artifact) for cap, p in sorted(job.parts.items())
                                   if cap not in job.scores]))
            audits = [(cid, c.spec, c.rubric, c.artifact or "") for cid in list(self.pending_audits)
                      if (c := self.w.contracts.get(cid)) is not None]
            reviews = [(cid, c.spec, c.rubric, c.artifact or "") for cid in list(self.pending_reviews)
                       if (c := self.w.contracts.get(cid)) is not None and c.status == ContractStatus.DELIVERED]
        tasks = [((jid, cap), spec, rubric, artifact) for jid, parts in jobs for cap, spec, rubric, artifact in parts]
        tasks += [(("audit", cid), spec, rubric, artifact) for cid, spec, rubric, artifact in audits]
        tasks += [(("review", cid), spec, rubric, artifact) for cid, spec, rubric, artifact in reviews]
        verdicts = dict(self.map_calls(lambda t: (t[0], self.try_grade(*t[1:])), tasks))
        with self.w.lock:
            for jid, parts in jobs:
                self.apply_job_grades(jid, [(cap, verdicts[(jid, cap)]) for cap, *_ in parts])
            for cid, *_ in audits:
                self.w.contract_net.settle_audit(cid, verdicts[("audit", cid)])
            for cid, *_ in reviews:
                self.w.contract_net.settle_review(cid, verdicts[("review", cid)])
            self.settle_deferred()

    def map_calls(self, fn, items: list) -> list:
        """Run model calls (outside the lock) up to `grading_workers` at a time; results in input order."""
        workers = self.w.params.runtime.grading_workers
        if workers <= 1 or len(items) <= 1:
            return [fn(i) for i in items]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items))

    def try_grade(self, spec: str, rubric: str, artifact: str):
        # a rule before any judgement: work citing archive passages that don't exist made them up
        cited = archive_citations(artifact or "")
        missing = [c for c in cited if self.w.archive.get(c) is None]
        with self._cite_lock:
            self.citations["valid"] += len(cited) - len(missing)
            self.citations["invalid"] += len(missing)
        if missing:
            return Grade(0.0, 0, f"cites archive passages that don't exist ({', '.join(missing[:3])}); a made-up "
                                 f"citation fails the part")
        try:
            return self.w.grader.grade(spec, rubric, artifact)
        except GradingError as e:
            return e

    def apply_job_grades(self, jid: JobId, graded: list) -> None:
        job = self.w.jobs.get(jid)
        if job is None or job.status != JobStatus.CLAIMED:
            self.awaiting_grade.pop(jid, None)
            return
        errors, defer = [], 0
        for cap, g in graded:
            if isinstance(g, GradingError):
                errors.append(str(g))
                continue
            try:
                # the commons pays for grading; when it can't, the prime whose job it is does
                self.charge(g, job=jid, part=cap, payers=("treasury", purse(job.prime)))
            except InsufficientFunds:
                self.awaiting_grade.pop(jid, None)
                self.w.board.fail(job, "no one could pay for grading")
                return
            job.record_score(cap, g.score)
            defer = max(defer, g.settle_after)
        if errors:
            self.awaiting_grade[jid] += 1
            if self.awaiting_grade[jid] >= self.w.params.market.grade_retries:
                self.awaiting_grade.pop(jid)
                self.w.board.fail(job, "the grader was unavailable")
            else:
                self.w.events.publish(ev.GradingDelayed(job, errors[0]))
            return
        self.awaiting_grade.pop(jid, None)
        if defer and job.passed(self.w.params.market.pass_score):
            job.defer(until=self.w.cycle + defer)
            self.deferred.add(jid)
            self.w.events.publish(ev.JobDeferred(job))
            return
        self.w.board.finish(job)

    def settle_deferred(self) -> None:
        """Outcomes whose time has come: ask the grader again (if it can), then pay or fail. Under the lock."""
        for jid in sorted(self.deferred):
            job = self.w.jobs.get(jid)
            if job is None or job.status != JobStatus.GRADED:
                self.deferred.discard(jid)
                continue
            if self.w.cycle < job.settle_at:
                continue
            self.deferred.discard(jid)
            later = self.w.grader.settle(job) if hasattr(self.w.grader, "settle") else None
            for cap, score in (later or {}).items():
                job.record_score(cap, score)
            self.w.board.finish(job)

    def charge(self, g: Grade, *, job: str, part: str, payers: tuple[str, ...], audit: str | None = None) -> Grade:
        """Pay for one grade: the notional cost from the first payer that can afford it, and, if a billed
        model did the work, the real bill in USD as well. Under the lock."""
        if g.cost:
            payer = next((a for a in payers if self.w.ledger.balance(a) >= g.cost), payers[-1])
            self.w.ledger.transfer(payer, "compute", g.cost, cycle=self.w.cycle, kind="grading", memo=audit or job)
        if g.model and g.usage:
            self.w.events.publish(ev.ModelCalled("grader", "grader", g.model, g.usage.input_tokens, g.usage.output_tokens,
                                                 g.cache_hit, g.cost, g.ms, g.real))
            if g.real:
                self.w.meter.record_real("grader", g.price_as or g.model, g.usage, cycle=self.w.cycle)
        self.w.events.publish(ev.PartGraded(job, part, g, audit))
        return g
