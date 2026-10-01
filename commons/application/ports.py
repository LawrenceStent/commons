"""Ports: what the society needs from the outside world, as interfaces it owns. Adapters implement them
(runtime/backends.py for models, runtime/web.py for the web); the society never imports an adapter.

The model port: one interface, two kinds of call.
    structured(...)  one answer matching a JSON schema (graders, appraisers, founding)
    chat(...)        a tool-calling turn (stewards) or plain text (members)

`chat` takes a backend-neutral conversation:
    {"role": "user", "text": str}
    {"role": "assistant", "text": str, "tool_calls": [ToolCall], "raw": <backend-native content>}
    {"role": "tool", "results": [ToolResult]}
and tools as {"name", "description", "input_schema"}. Every completion reports token usage and whether it was real,
so the meter can charge the society (always) and book the real bill (only when there is one). Failures raise
ModelError with a readable reason; callers decide whether to retry.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Protocol

from commons.domain.compute import Usage


class ModelError(Exception):
    """The backend couldn't produce a usable answer: unreachable, refused, truncated or malformed."""


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]  # the parsed structured output
    usage: Usage
    model: str  # what actually answered
    price_as: str  # the price-table entry this call is charged at
    real: bool  # True when someone is billed for it
    ms: int
    text: str = ""

    @property
    def cache_hit(self) -> float | None:
        read = self.usage.cache_read_input_tokens
        total = read + self.usage.input_tokens + self.usage.cache_creation_input_tokens
        return read / total if total else None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Turn:
    text: str
    tool_calls: tuple[ToolCall, ...]
    stop: str  # tool_use | end_turn | max_tokens | refusal
    usage: Usage
    model: str
    price_as: str
    real: bool
    ms: int
    raw: Any = None  # backend-native assistant content, replayed as is

    @property
    def cache_hit(self) -> float | None:
        read = self.usage.cache_read_input_tokens
        total = read + self.usage.input_tokens + self.usage.cache_creation_input_tokens
        return read / total if total else None

    def as_message(self) -> dict[str, Any]:
        return {"role": "assistant", "text": self.text, "tool_calls": list(self.tool_calls), "raw": self.raw}


class ModelBackend(Protocol):
    name: str
    real: bool

    def structured(self, *, model: str, system: str, prompt: str, schema: dict[str, Any],
                   max_tokens: int = 1024) -> Completion: ...

    def chat(self, *, model: str, system: list[str], messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, max_tokens: int = 4096, reasoning: bool = True) -> Turn: ...
    # reasoning=False asks the model to answer without thinking first (members write; they don't plan)


# ── the web ────────────────────────────────────────────────────
class WebError(Exception):
    """A read that couldn't be done (a refusal, or the site failed). The message is safe to show an agent."""


@dataclass(frozen=True)
class Page:
    url: str  # the final url, after redirects
    title: str
    text: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class WebPort(Protocol):
    """Reads only, behind the operator's allowlist (which the adapter enforces on its own, as a second check)."""
    search_host: str | None  # the host searches go to; None when there's no search

    def set_hosts(self, hosts) -> None: ...

    def fetch(self, url: str) -> Page: ...

    def search(self, query: str, k: int = 5) -> list[SearchResult]: ...


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
