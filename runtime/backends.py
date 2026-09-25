"""Model backends: one interface, three ways to get a completion.

    AnthropicBackend   the Claude API via the official SDK. Real calls, billed in USD.
    LMStudioBackend    a local model behind LM Studio's server (http://localhost:1234). Free;
                       the society is still charged notionally, priced as `price_as`.
    FakeBackend        scripted answers for tests. Spends nothing.

Every completion reports token usage and whether it was real, so the meter can charge the
society (always) and book the real bill (only when there is one). Failures raise ModelError
with a readable reason; callers decide whether to retry.

Two kinds of call:
    structured(...)  one answer matching a JSON schema (the grader)
    chat(...)        a tool-calling turn (stewards) or plain text (members)

`chat` takes a backend-neutral conversation:
    {"role": "user", "text": str}
    {"role": "assistant", "text": str, "tool_calls": [ToolCall], "raw": <backend-native content>}
    {"role": "tool", "results": [ToolResult]}
and tools as {"name", "description", "input_schema"}. Each backend translates. An assistant
message keeps its native `raw` content so a backend can replay it exactly; models that think
require their own blocks back unchanged.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from substrate.meter import Usage


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
             tools: list[dict[str, Any]] | None = None, max_tokens: int = 4096) -> Turn: ...


def _check(data: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Minimal guard for backends that can't enforce a schema: an object with the required keys."""
    if not isinstance(data, dict) or any(k not in data for k in schema.get("required", [])):
        raise ModelError(f"answer doesn't match the schema: {str(data)[:200]}")
    return data


# ── Anthropic ──────────────────────────────────────────────────
class AnthropicBackend:
    name = "anthropic"
    real = True

    def __init__(self, client: Any = None, timeout: float = 60.0, max_retries: int = 2):
        self._client = client
        self.timeout, self.max_retries = timeout, max_retries

    @property
    def client(self):
        if self._client is None:
            import anthropic  # imported lazily so simulations never need credentials

            self._client = anthropic.Anthropic(timeout=self.timeout, max_retries=self.max_retries)
        return self._client

    def structured(self, *, model, system, prompt, schema, max_tokens=1024) -> Completion:
        import anthropic

        t = time.perf_counter()
        try:
            r = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                # the system prompt is frozen, so it caches once it is long enough to be cacheable
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.RateLimitError as e:
            raise ModelError(f"rate limited by the API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ModelError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ModelError(f"couldn't reach the API: {e}") from e
        ms = round((time.perf_counter() - t) * 1000)
        u = r.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_input_tokens=u.cache_read_input_tokens or 0,
            cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        )
        if r.stop_reason in ("refusal", "max_tokens"):
            raise ModelError(f"the model stopped early ({r.stop_reason})")
        text = next((b.text for b in r.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ModelError(f"unparseable answer: {text[:200]}") from e
        return Completion(_check(data, schema), usage, r.model, model, True, ms, text)


    def chat(self, *, model, system, messages, tools=None, max_tokens=4096) -> Turn:
        """`system` is a list of blocks; every block is marked cacheable (at most 4 breakpoints),
        so a frozen preamble followed by a per-community charter caches in two layers."""
        import anthropic

        wire = []
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                content = m.get("raw")
                if content is None:
                    content = ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in m.get("tool_calls", [])]
                wire.append({"role": "assistant", "content": content})
            else:  # all results of one round in one user message, as parallel tool use requires
                wire.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                    for r in m["results"]]})
        kw: dict[str, Any] = {}
        if tools:
            kw["tools"] = tools
        t = time.perf_counter()
        try:
            r = self.client.messages.create(
                model=model, max_tokens=max_tokens, messages=wire,
                system=[{"type": "text", "text": b, "cache_control": {"type": "ephemeral"}} for b in system[:4]],
                **kw)
        except anthropic.RateLimitError as e:
            raise ModelError(f"rate limited by the API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ModelError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ModelError(f"couldn't reach the API: {e}") from e
        ms = round((time.perf_counter() - t) * 1000)
        u = r.usage
        usage = Usage(u.input_tokens or 0, u.output_tokens or 0, u.cache_read_input_tokens or 0,
                      u.cache_creation_input_tokens or 0)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = tuple(ToolCall(b.id, b.name, dict(b.input)) for b in r.content if b.type == "tool_use")
        return Turn(text, calls, r.stop_reason or "end_turn", usage, r.model, model, True, ms, raw=r.content)


# ── LM Studio ──────────────────────────────────────────────────
class LMStudioBackend:
    """LM Studio's OpenAI-compatible server. Start it with `lms server start` and load a model
    first (`lms load <model>`); check memory before you do (see the resource guardrails)."""

    name = "lmstudio"
    real = False

    def __init__(self, base_url: str = "http://localhost:1234/v1", price_as: str = "claude-haiku-4-5",
                 timeout: float = 180.0):
        self.base_url, self.price_as, self.timeout = base_url.rstrip("/"), price_as, timeout

    def structured(self, *, model, system, prompt, schema, max_tokens=1024) -> Completion:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        r, ms = self._post(body)
        try:
            choice = r["choices"][0]
            text = choice["message"]["content"] or ""
            if choice.get("finish_reason") == "length":
                raise ModelError("the model ran out of tokens")
            data = json.loads(text)
        except (KeyError, IndexError, ValueError) as e:
            raise ModelError(f"unusable answer from LM Studio: {str(r)[:200]}") from e
        u = r.get("usage") or {}
        usage = Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))
        return Completion(_check(data, schema), usage, r.get("model", model), self.price_as, False, ms, text)

    def chat(self, *, model, system, messages, tools=None, max_tokens=4096) -> Turn:
        wire: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(system)}]
        for m in messages:
            if m["role"] == "user":
                wire.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("text") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.input)}}
                                         for c in m["tool_calls"]]
                wire.append(msg)
            else:
                wire += [{"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in m["results"]]
        body: dict[str, Any] = {"model": model, "messages": wire, "max_tokens": max_tokens, "temperature": 0.3}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        r, ms = self._post(body)
        try:
            choice = r["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError) as e:
            raise ModelError(f"unusable answer from LM Studio: {str(r)[:200]}") from e
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = {"_unparseable": c["function"].get("arguments", "")[:200]}
            calls.append(ToolCall(c.get("id") or f"call_{i}", c["function"]["name"], args if isinstance(args, dict) else {}))
        stop = {"tool_calls": "tool_use", "length": "max_tokens"}.get(choice.get("finish_reason"), "end_turn")
        if calls:
            stop = "tool_use"
        u = r.get("usage") or {}
        usage = Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))
        return Turn(msg.get("content") or "", tuple(calls), stop, usage, r.get("model", model), self.price_as, False, ms)

    def _post(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                r = json.load(resp)
        except urllib.error.HTTPError as e:
            raise ModelError(f"LM Studio returned {e.code}: {e.read()[:200]!r}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ModelError(f"couldn't reach LM Studio at {self.base_url} (is the server running and a model loaded?): {e}") from e
        return r, round((time.perf_counter() - t) * 1000)


# ── Fake ───────────────────────────────────────────────────────
@dataclass
class FakeBackend:
    """Answers `structured` with `respond(system, prompt, schema)` and `chat` with
    `converse(system, messages, tools)`, which returns a Turn-like dict: {"text", "tool_calls":
    [(name, input), ...]}. Usage is estimated at 4 characters a token. Set `real=True` to exercise
    the real-money path in tests without spending anything."""

    respond: Callable[[str, str, dict], dict] | None = None
    converse: Callable[[list[str], list[dict], list[dict] | None], dict] | None = None
    real: bool = False
    price_as: str = "claude-haiku-4-5"
    name: str = "fake"
    calls: list[tuple[str, str]] = field(default_factory=list)
    chats: list[tuple] = field(default_factory=list)

    def structured(self, *, model, system, prompt, schema, max_tokens=1024) -> Completion:
        self.calls.append((system, prompt))
        data = self.respond(system, prompt, schema)
        if isinstance(data, Exception):
            raise data
        text = json.dumps(data)
        usage = Usage(input_tokens=(len(system) + len(prompt)) // 4, output_tokens=len(text) // 4)
        return Completion(_check(data, schema), usage, model, self.price_as, self.real, 1, text)

    def chat(self, *, model, system, messages, tools=None, max_tokens=4096) -> Turn:
        self.chats.append((system, messages, tools))
        out = self.converse(system, messages, tools)
        if isinstance(out, Exception):
            raise out
        calls = tuple(ToolCall(f"c{len(self.chats)}_{i}", name, dict(args))
                      for i, (name, args) in enumerate(out.get("tool_calls", [])))
        prompt = sum(len(b) for b in system) + sum(len(m.get("text") or "") + sum(len(r.content) for r in m.get("results", []))
                                                   for m in messages)
        usage = Usage(input_tokens=prompt // 4, output_tokens=max(1, len(out.get("text", "")) // 4 + 20 * len(calls)))
        return Turn(out.get("text", ""), calls, "tool_use" if calls else "end_turn", usage, model, self.price_as,
                    self.real, 1)
