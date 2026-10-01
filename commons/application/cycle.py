"""The cycle: everything that happens in one cycle of a society, in order.

Each phase either runs under the world's lock (it changes state, one thing at a time) or outside it (it waits on
models or the web, and takes the lock itself only to apply what came back). Turns are the one phase that can run in
parallel: with `parallel_turns`, model calls overlap and every action still takes the lock.

    start         the cycle number; the operator's folder re-read; the gate's day begins; the bus's allowances reset
    fund          the economy tops up its pool, if it keeps one
    ratings       your new ratings become evidence
    floor         the treasury tops up poor purses
    wake          each co-op decides how many members to wake, and pays for them
    deadlines     anything past its deadline expires, fails or defaults
    proposals     spawn and merge proposals past their deadline expire
    post          new jobs go up on the board
    order         a random turn order (turn order must not decide who wins)
    appraise      venture proposals are appraised (outside the lock)
    web           requests the operator approved run (outside the lock)
    turns         each active co-op sees an observation and acts
    allocate      claims are allocated: most trusted, best fitting, least loaded
    grade         submitted work, deliveries and audits are graded (model calls outside the lock)
    pay           work waiting for the end of the cycle is paid
    gossip        every few cycles, co-ops relay what they've seen
    close         evidence decays, the bus compacts, old records are pruned, the cycle is recorded
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from commons.application.population import expire_proposals

if TYPE_CHECKING:
    from commons.application.world import World


@dataclass(frozen=True)
class Phase:
    name: str
    run: Callable[[World], None]
    locked: bool = True  # False: it manages the lock itself


def _start(w: World) -> None:
    w.cycle += 1
    w.rep.cycle = w.cycle
    if w.operator.reload():  # your directives, context and limits, re-read every cycle
        w.hub.emit("operator.update", w.cycle, coops=sorted(w.operator.views), errors=w.operator.errors)
        w.gate.policy = w.operator.gate
        if w.web:
            w.web.set_hosts(w.gate.policy.allow_hosts)
    w._gate_cycle()
    w.bus.begin_cycle(w.cycle)
    w._stats = {n: Counter() for n in w.communities}


def _deadlines(w: World) -> None:
    w.board.expire_overdue()
    w.contract_net.expire_overdue()


def _order(w: World) -> None:
    w.turn_order = w._active()
    w.rng.shuffle(w.turn_order)  # turn order must not decide who wins


def _turns(w: World) -> None:
    order = w.turn_order
    if w.params.parallel_turns and len(order) > 1:
        # the lock is released here: each action takes it, model calls don't
        with ThreadPoolExecutor(max_workers=w.params.parallel_workers) as pool:
            for f in [pool.submit(w._turn, c) for c in order]:
                f.result()  # re-raise anything a turn raised (a kill-switch, say)
    else:
        with w.lock:
            for c in order:
                w._turn(c)


def _gossip(w: World) -> None:
    if w.cycle % w.params.gossip_every == 0:
        w._gossip()


def _close(w: World) -> None:
    w.rep.tick()
    w.bus.compact()
    w.board.prune()
    w.contract_net.prune()
    w._record()


PHASES: tuple[Phase, ...] = (
    Phase("start", _start),
    Phase("fund", lambda w: w.payments.fund()),
    Phase("ratings", lambda w: w.rating_desk.apply()),
    Phase("floor", lambda w: w._floor()),
    Phase("wake", lambda w: w._upkeep()),
    Phase("deadlines", _deadlines),
    Phase("proposals", expire_proposals),
    Phase("post", lambda w: w.board.post()),
    Phase("order", _order),
    Phase("appraise", lambda w: w.venture_desk.appraise(), locked=False),
    Phase("web", lambda w: w._run_approved_web(), locked=False),
    Phase("turns", _turns, locked=False),
    Phase("allocate", lambda w: w.board.allocate()),
    Phase("grade", lambda w: w.grading.settle(), locked=False),
    Phase("pay", lambda w: w.payments.settle_queue()),
    Phase("gossip", _gossip),
    Phase("close", _close),
)


def run_cycle(w: World) -> None:
    for phase in PHASES:
        if phase.locked:
            with w.lock:
                phase.run(w)
        else:
            phase.run(w)
