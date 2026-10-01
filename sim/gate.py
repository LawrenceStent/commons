"""The gate: nothing an agent does reaches the outside world unless your policy allows it or you approved it.

This is the first enforcement point, in the tool layer. The second is the network layer (runtime/web.py), which
refuses any host not on the allowlist whatever the gate says, so a mistake in one is caught by the other.

Every outside-world tool has a risk class:

    read      searching and reading public web pages (web_search, web_fetch)
    contact   messaging or emailing anyone                      (no tools yet: always ask or deny)
    publish   posting, listing or submitting anything anywhere  (no tools yet: always ask or deny)
    spend     paying for anything                               (no tools yet: always ask or deny)

Your policy, in the operator folder's config.toml:

    [gate]
    read = "ask"                 # ask (default) | allow | deny. Only reads may ever be "allow"
    allow_hosts = ["en.wikipedia.org", "*.who.int"]   # the egress allowlist; nothing else is reachable
    search = "wikipedia"         # the search provider, or "none"
    per_cycle = 6                # web calls per co-op per cycle, a rule
    ttl = 10                     # cycles a request waits for you before it expires

With "ask", a call becomes a request and the agent is told it's waiting. You approve or deny requests from the
dashboard, in batches grouped by co-op, tool and host, or from the command line (`python -m sim.approve NAME`).
"Always" makes a standing approval for that co-op and host. Approved requests run at the start of the next cycle,
and the agent that asked is told the result. Every request and decision is in the activity log.

Headless runs of a founded society write requests to `gate-requests.jsonl` in its folder and read your decisions
from `gate.jsonl` there, one per line: {"id": "<run>/G3", "decision": "approve" | "deny", "always": false}.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from substrate.jsonl import JsonlLog

RISKS = ("read", "contact", "publish", "spend")
TOOLS = {"web_search": "read", "web_fetch": "read"}  # tool -> risk class
POLICIES = ("ask", "allow", "deny")
SEARCH = ("wikipedia", "none")


class GateError(ValueError):
    pass


@dataclass(frozen=True)
class GatePolicy:
    read: str = "ask"
    contact: str = "deny"
    publish: str = "deny"
    spend: str = "deny"
    allow_hosts: tuple[str, ...] = ()
    search: str = "wikipedia"
    per_cycle: int = 6
    ttl: int = 10

    @classmethod
    def parse(cls, cfg: dict) -> GatePolicy:
        known = set(RISKS) | {"allow_hosts", "search", "per_cycle", "ttl"}
        if unknown := set(cfg) - known:
            raise GateError(f"unknown [gate] keys {sorted(unknown)}; allowed: {sorted(known)}")
        for risk in RISKS:
            v = cfg.get(risk, getattr(cls, risk))
            if v not in POLICIES:
                raise GateError(f"[gate] {risk} must be one of {', '.join(POLICIES)}")
            if risk != "read" and v == "allow":
                raise GateError(f"[gate] {risk} can't be \"allow\": anything that isn't a read always needs you")
        hosts = cfg.get("allow_hosts", [])
        if not isinstance(hosts, list) or not all(isinstance(h, str) and h.strip() for h in hosts):
            raise GateError("[gate] allow_hosts must be a list of host names")
        if cfg.get("search", "wikipedia") not in SEARCH:
            raise GateError(f"[gate] search must be one of {', '.join(SEARCH)}")
        return cls(**{**{k: cfg[k] for k in RISKS if k in cfg}, "allow_hosts": tuple(h.strip().lower() for h in hosts),
                      "search": cfg.get("search", "wikipedia"), "per_cycle": int(cfg.get("per_cycle", 6)),
                      "ttl": int(cfg.get("ttl", 10))})

    def allows_host(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return any(host == a or (a.startswith("*.") and (host == a[2:] or host.endswith(a[1:]))) for a in self.allow_hosts)

    def describe(self) -> str:
        if not self.allow_hosts or self.read == "deny":
            return ""
        how = {"ask": "each read waits for the operator's approval (run at the start of a later cycle)",
               "allow": "reads run at once"}[self.read]
        return (f"WEB: you and your members may search ({self.search}) and read pages on {', '.join(self.allow_hosts)}; "
                f"{how}; at most {self.per_cycle} web calls a cycle. Fetched pages join the archive: cite them as "
                f"[archive: <id>].")


@dataclass
class Request:
    id: str
    coop: str
    actor: str
    tool: str
    risk: str
    target: str  # the url, or the search query
    host: str
    cycle: int
    status: str = "pending"  # pending | approved | denied | expired | done | failed
    always: bool = False
    reason: str = ""
    result: str = ""

    @property
    def group(self) -> tuple[str, str, str]:
        return (self.coop, self.tool, self.host)


class Gate:
    def __init__(self, policy: GatePolicy | None = None, folder: str | Path | None = None, run: str = "run"):
        self.policy = policy or GatePolicy()
        self.folder, self.run = (Path(folder) if folder else None), run
        self.requests: dict[str, Request] = {}
        self.standing: set[tuple[str, str]] = set()  # (co-op, host) you approved "always"
        self.used: Counter[str] = Counter()  # web calls this cycle, per co-op
        self.errors: list[str] = []
        self._seq = 0
        self._requests = JsonlLog(self.folder / "gate-requests.jsonl" if self.folder else None)
        self._decisions = JsonlLog(self.folder / "gate.jsonl" if self.folder else None)

    def begin_cycle(self) -> None:
        self.used = Counter()

    # ── asking ─────────────────────────────────────────────────
    def ask(self, coop: str, actor: str, tool: str, target: str, host: str, cycle: int) -> tuple[str, Request | str]:
        """("allow", request) to run now; ("pending", request) queued for you; ("deny", reason)."""
        risk = TOOLS.get(tool)
        if risk is None:
            return "deny", f"{tool} is not a tool the gate knows"
        policy = getattr(self.policy, risk)
        if policy == "deny":
            return "deny", f"the operator doesn't allow {risk} tools"
        if not self.policy.allows_host(host):
            hosts = ", ".join(self.policy.allow_hosts) or "none"
            return "deny", f"{host or 'that address'} is not on the operator's allowlist (allowed: {hosts})"
        if self.used[coop] >= self.policy.per_cycle:
            return "deny", f"you've used your {self.policy.per_cycle} web calls this cycle"
        waiting = next((r for r in self.requests.values() if r.status in ("pending", "approved") and r.coop == coop
                        and r.tool == tool and r.target == target), None)
        if waiting:
            return "pending", waiting
        self.used[coop] += 1
        self._seq += 1
        r = Request(f"G{self._seq}", coop, actor, tool, risk, target, host, cycle)
        self.requests[r.id] = r
        if policy == "allow" or (coop, host) in self.standing:
            r.status, r.reason = "approved", "allowed by policy" if policy == "allow" else "standing approval"
            return "allow", r
        self._write(r)
        return "pending", r

    # ── deciding ───────────────────────────────────────────────
    def decide(self, ids, approve: bool, always: bool = False, reason: str = "") -> list[Request]:
        """Approve or deny pending requests. `always` also approves this co-op's future reads from each host."""
        done = []
        for rid in ids:
            r = self.requests.get(rid)
            if r is None or r.status != "pending":
                continue
            r.status, r.reason, r.always = ("approved" if approve else "denied"), reason, bool(approve and always)
            if r.always:
                self.standing.add((r.coop, r.host))
            done.append(r)
        return done

    def revoke(self, coop: str, host: str) -> bool:
        if (coop, host) in self.standing:
            self.standing.discard((coop, host))
            return True
        return False

    def expire(self, cycle: int) -> list[Request]:
        out = []
        for r in self.requests.values():
            if r.status == "pending" and cycle - r.cycle >= self.policy.ttl:
                r.status, r.reason = "expired", f"no decision within {self.policy.ttl} cycles"
                out.append(r)
        return out

    def pending(self) -> list[Request]:
        return [r for r in self.requests.values() if r.status == "pending"]

    def approved(self) -> list[Request]:
        return [r for r in self.requests.values() if r.status == "approved"]

    def groups(self) -> list[dict]:
        """Pending requests batched by (co-op, tool, host), for approving together."""
        by: dict[tuple, list[Request]] = {}
        for r in self.pending():
            by.setdefault(r.group, []).append(r)
        return [{"coop": c, "tool": t, "host": h, "ids": [r.id for r in rs], "targets": [r.target for r in rs][:10]}
                for (c, t, h), rs in sorted(by.items())]

    # ── files, for headless runs ───────────────────────────────
    def _write(self, r: Request) -> None:
        self._requests.append({**asdict(r), "id": f"{self.run}/{r.id}"})

    def reload(self) -> list[Request]:
        """Your decisions from gate.jsonl since the last read (this run's requests only)."""
        out = []
        for line in self._decisions.read_new():
            try:
                d = json.loads(line)
                run, _, rid = str(d["id"]).rpartition("/")
                if d["decision"] not in ("approve", "deny"):
                    raise ValueError("decision must be approve or deny")
            except (ValueError, KeyError, TypeError) as e:
                self.errors.append(f"gate.jsonl: {e}: {line[:80]}")
                continue
            if run == self.run:
                out += self.decide([rid], d["decision"] == "approve", bool(d.get("always")), str(d.get("reason", "")))
        return out


def pending_in(folder: Path) -> list[dict]:
    """Requests in a society folder that have no decision yet (for the command line)."""
    decided = {d.get("id") for d in JsonlLog(folder / "gate.jsonl").read_all()}
    return [r for r in JsonlLog(folder / "gate-requests.jsonl").read_all() if r["id"] not in decided]


def record(folder: Path, request_id: str, approve: bool, always: bool = False, reason: str = "") -> None:
    JsonlLog(folder / "gate.jsonl").append({"id": request_id, "decision": "approve" if approve else "deny",
                                            "always": always, "reason": reason})
