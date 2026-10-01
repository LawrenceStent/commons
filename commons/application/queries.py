"""Read models for the dashboard: what the page shows, built from the society's state and the telemetry hub's bounded
rings, so a snapshot's size doesn't grow with the length of the run. Reading changes nothing.

`snapshot(world, console)` is the whole page, one function per panel; `console` is the run's controls (running, speed,
why it paused, the memory limit). `community_view` is one co-op's drill-down.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from commons.domain.status import LIVE_CONTRACT, ContractStatus, GoalStatus, JobStatus, ProposalStatus, RequestStatus
from commons.substrate.ledger import purse

if TYPE_CHECKING:
    from commons.application.society import World

SERIES_POINTS = 120  # points per sparkline, however long the run


def snapshot(w: World, console: dict[str, Any]) -> dict:
    hub = w.hub
    cycles = hub.recent("world.cycle", n=hub.ring)
    return {
        "run": _run(w, console), "money": _money(w), "gate": _gate(w), "society": _society(w),
        "treasury_series": _downsample([[e.cycle, e.fields["treasury"]] for e in cycles]),
        "communities": _communities(w, cycles), "reputation": _reputation(w), "market": _market(w),
        "contracts": _contracts(w), "ledger": _ledger(w), "bus": _bus(w, cycles), "population": _population(w),
        "activity": [asdict(e) for e in w.activity.recent(150)][::-1], "plans": _plans(w), "operator": _operator(w),
        "knowledge": [{"id": pb.id, "author": pb.author, "capability": pb.capability, "title": pb.title, "uses": pb.uses}
                      for pb in w.library.values()],
        "llm": _llm(w), "grader": {"recent": _events(w, "grader.grade")[-10:][::-1], "count": hub.counts["grader.grade"]},
        "host": _host(w), "events": dict(hub.counts),
    }


def community_view(w: World, name: str) -> dict:
    c = w.communities[name]
    return {"name": name, "charter": c.charter, "purse": w.ledger.balance(purse(name)), "strategy": c.strategy.name,
            "journal": list(w.journal[name]), "inbox": [e.__dict__ for e in w.inbox[name]],
            "transcripts": list(w.transcripts.get(name, [])),
            "activity": [asdict(e) for e in w.activity.recent(80, community=name)][::-1],
            "events": community_detail(w, name)}


def community_detail(w: World, name: str, n: int = 60) -> list[dict]:
    """Recent events that involve `name` in any field."""
    def involves(v) -> bool:
        if v == name:
            return True
        if isinstance(v, dict):
            return name in v or any(involves(x) for x in v.values())
        if isinstance(v, (list, tuple)):
            return any(involves(x) for x in v)
        return False

    hits = [e for e in w.hub.recent(n=w.hub.ring) if e.kind != "world.cycle" and involves(e.fields)]
    return [_ev(e) for e in hits[-n:][::-1]]


def own_directives(w: World, coop: str | None) -> str:
    """The text of one directives file as written (all.md, or coops/<name>.md), for editing."""
    if not w.operator.root:
        return ""
    p = w.operator.root / ("all.md" if coop is None else f"coops/{coop}.md")
    return p.read_text() if p.exists() else ""


# ── helpers ────────────────────────────────────────────────────
def _downsample(xs: list, n: int = SERIES_POINTS) -> list:
    if len(xs) <= n:
        return xs
    step = len(xs) / n
    return [xs[int(i * step)] for i in range(n - 1)] + [xs[-1]]


def _ev(e) -> dict:
    return {**e.fields, "seq": e.seq, "kind": e.kind, "cycle": e.cycle}


def _events(w: World, kind: str, n: int | None = None) -> list[dict]:
    return [_ev(e) for e in w.hub.recent(kind, n=n or w.hub.ring)]


# ── panels ─────────────────────────────────────────────────────
def _run(w: World, console: dict) -> dict:
    return {"cycle": w.cycle, "running": console["running"], "speed": console["speed"],
            "pause_reason": console["reason"], "seed": w.params.run.seed, "reputation": w.params.run.reputation,
            "jobs_done": w.jobs_done, "jobs_failed": w.jobs_failed, "treasury": w.ledger.balance("treasury"),
            "halted": w.meter.halted, "spent_today": w.meter.spent_today, "ceiling": w.meter.daily_ceiling,
            "rss_limit": console["rss_limit"]}


def _money(w: World) -> dict:
    return {"currency": w.ledger.currency, "real": w.ledger.real(), "real_spent_today": w.meter.real_spent_today,
            "real_ceiling": w.meter.real_ceiling}


def _gate(w: World) -> dict:
    recent = [r for r in list(w.gate.requests.values())[-20:] if r.status != RequestStatus.PENDING][::-1]
    return {"web": bool(w.web), "policy": asdict(w.gate.policy), "groups": w.gate.groups(),
            "standing": sorted([c, h] for c, h in w.gate.standing),
            "recent": [{"id": r.id, "coop": r.coop, "tool": r.tool, "target": r.target, "status": r.status,
                        "result": r.result, "cycle": r.cycle} for r in recent]}


def _society(w: World) -> dict:
    return {"pack": w.pack.title, "economy": w.payment.name, "scorecard": w.scorecard,
            "grants": w.ledger.balance(w.payment.pool) if w.payment.pool else None,
            "grant_budget": w.params.money.grant_budget}


def _communities(w: World, cycles: list) -> list[dict]:
    last = cycles[-1].fields if cycles else {"communities": {}}
    return [{"name": name, "strategy": c.strategy.name, "capabilities": sorted(c.capabilities), "members": c.members,
             **last["communities"].get(name, {}),
             "won_total": sum(s.won for s in w.history[name]),
             "ok_total": sum(s.delivered_ok for s in w.history[name]),
             "compute": w.meter.by_community.get(name, 0), "efficiency": w.recorder.efficiency(name),
             "rate_limited": w.bus.rejected.get(name, 0), "royalties": w.royalties_paid.get(name, 0),
             "purse_series": _downsample([[e.cycle, e.fields["communities"][name]["purse"]] for e in cycles
                                          if name in e.fields["communities"]]),
             "parent": c.parent, "dissolved": c.dissolved}
            for name, c in w.communities.items()]


def _reputation(w: World) -> dict:
    names = list(w.communities)
    trust = {o: {s: (None if o == s else round(w.rep.trust(o, s), 3)) for s in names} for o in names}
    return {"names": names, "trust": trust, "attests": _events(w, "reputation.attest", 12)[::-1]}


def _market(w: World) -> dict:
    recent = [e for e in _events(w, "market.job", 60) if e["stage"] != "posted"][-15:][::-1]
    return {"recent": recent, "done": w.jobs_done, "failed": w.jobs_failed, "expired": w.jobs_expired,
            "board": sum(j.status == JobStatus.OPEN for j in w.jobs.values()),
            "in_progress": sum(j.status == JobStatus.CLAIMED for j in w.jobs.values()),
            "reward": w.params.market.job_reward}


def _contracts(w: World) -> dict:
    closed = tuple(s for s in ContractStatus if s not in LIVE_CONTRACT)
    contracts = [e for e in _events(w, "contract.stage") if e["stage"] in closed]
    return {"recent": contracts[-15:][::-1], "stages": Counter(c["stage"] for c in contracts), "window": len(contracts),
            "live": Counter(c.status for c in w.contracts.values() if c.status in LIVE_CONTRACT)}


def _ledger(w: World) -> dict:
    posts = _events(w, "ledger.post")
    flows: Counter[str] = Counter()
    for p in posts:
        if p["currency"] == w.ledger.currency:  # never add real dollars and credits together
            flows[p["type"]] += sum(n for _, n in p["legs"] if n > 0)
    return {"recent": posts[-15:][::-1], "flows": flows, "window": len(posts), "compute": w.ledger.balance("compute"),
            "market": w.ledger.balance("market")}


def _bus(w: World, cycles: list) -> dict:
    last = cycles[-1].fields if cycles else {"bus_sent": {}}
    prev = cycles[-2].fields if len(cycles) > 1 else {"bus_sent": {}}
    return {"sent": last["bus_sent"],
            "last_cycle": {f: n - prev["bus_sent"].get(f, 0) for f, n in last["bus_sent"].items()},
            "rate_limited": dict(w.bus.rejected), "tail": _events(w, "bus.publish", 20)[::-1]}


def _population(w: World) -> dict:
    return {"recent": _events(w, "population.", 15)[::-1],
            "open": [{"id": x.id, "kind": x.kind, "proposer": x.proposer, "detail": x.role or x.target,
                      "deadline": x.deadline} for x in w.proposals.values() if x.status == ProposalStatus.OPEN],
            "living": sum(not c.dissolved for c in w.communities.values()),
            "members": sum(c.members for c in w.communities.values()),
            "limits": {"members": w.params.population.max_members,
                       "communities": w.params.population.max_communities}}


def _plans(w: World) -> dict:
    def goal(n, g):
        return {"community": n, "id": g.id, "title": g.title, "status": g.status, "progress": round(g.progress, 3),
                "created": g.created, "updated": g.updated, "outcome": g.outcome,
                "steps": [{"text": s.text, "done": s.done, "note": s.note} for s in g.steps]}

    return {
        "goals": [goal(n, g) for n, p in w.plans.items()
                  for g in sorted(p.goals.values(), key=lambda g: (g.status != GoalStatus.ACTIVE, -g.updated))],
        "ideas": [{"community": n, **asdict(i)} for n, p in w.plans.items() for i in p.ideas][-40:][::-1],
        "ventures": [{"id": v.id, "proposer": v.proposer, "title": v.title, "pitch": v.pitch, "status": v.status,
                      "score": v.score, "reward": v.reward, "reason": v.reason, "job_id": v.job_id, "cycle": v.cycle,
                      "parts": [c for c, _, _ in v.parts]} for v in list(w.ventures.values())[-30:]][::-1],
        "jobs": [_job(w, j) for j in w.jobs.values() if j.status == JobStatus.CLAIMED],
    }


def _job(w: World, j) -> dict:
    def state(cap, part):
        if part.artifact is not None:
            return "done"
        return next((c.status for c in w.contracts.values()
                     if c.job_id == j.id and c.capability == cap and c.status in LIVE_CONTRACT), "open")

    return {"id": j.id, "title": j.title, "prime": j.prime, "deadline": j.deadline, "reward": j.reward,
            "awaiting_grade": j.id in w.grading.awaiting_grade,
            "parts": [{"capability": cap, "done": part.artifact is not None, "state": state(cap, part)}
                      for cap, part in sorted(j.parts.items())]}


def _operator(w: World) -> dict:
    return {"enabled": w.operator.root is not None, "folder": str(w.operator.root) if w.operator.root else None,
            "errors": list(w.operator.errors),
            "coops": [{"name": n, "directives": v.directives, "own": own_directives(w, n), "limits": v.limits.describe(),
                       "context": [name for name, _ in v.context], "runtime": v.runtime}
                      for n in list(w.communities) for v in [w.operator.view(n)]],
            "all": own_directives(w, None)}


def _llm(w: World) -> dict:
    llm = _events(w, "llm.call")
    return {"recent": llm[-10:][::-1], "calls": w.hub.counts["llm.call"], "cost": sum(c.get("cost", 0) for c in llm)}


def _host(w: World) -> dict:
    hosts = w.hub.recent("host.sample", n=w.hub.ring)
    return {**(hosts[-1].fields if hosts else {}),
            "rss_series": _downsample([[round(e.at), e.fields["rss"]] for e in hosts])}
