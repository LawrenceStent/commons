"""The gate's rules: risk classes, the operator's policy, and what a request is. See application/gate.py."""

from __future__ import annotations

from dataclasses import dataclass

from commons.domain.status import RequestStatus

RISKS = ("read", "contact", "publish", "spend", "govern")  # govern: a co-op changing its own constitution
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
    govern: str = "ask"
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
    target: str  # the url, the search query, or what is acted on (an item, a co-op)
    host: str
    cycle: int
    status: RequestStatus = RequestStatus.PENDING
    always: bool = False
    reason: str = ""
    result: str = ""
    detail: str = ""  # everything that would go public or take effect, for you to read before deciding

    @property
    def group(self) -> tuple[str, str, str]:
        return (self.coop, self.tool, self.host)

