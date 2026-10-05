"""Model backends: one interface, three ways to get a completion.

    AnthropicBackend   the Claude API via the official SDK. Real calls, billed in USD.
    LMStudioBackend    a local model behind LM Studio's server (http://localhost:1234). Free;
                       the society is still charged notionally, priced as `price_as`.
    FakeBackend        scripted answers for tests. Spends nothing.

They implement the model port (commons/application/ports.py), which describes the calls and the conversation format.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from commons.application.ports import (  # the port, re-exported
    Completion,
    ModelBackend,
    ModelError,
    ToolCall,
    ToolResult,
    Turn,
)
from commons.domain.compute import Usage


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


    def chat(self, *, model, system, messages, tools=None, max_tokens=4096, reasoning=True) -> Turn:
        """`system` is a list of blocks; every block is marked cacheable (at most 4 breakpoints),
        so a frozen preamble followed by a per-community charter caches in two layers."""
        import anthropic

        wire = _anthropic_messages(messages)
        kw: dict[str, Any] = {}
        if tools:
            kw["tools"] = tools
        if not reasoning:
            kw["thinking"] = {"type": "disabled"}
        t = time.perf_counter()
        try:
            r = self.client.messages.create(
                model=model, max_tokens=max_tokens, messages=cast(Any, wire),  # the SDK's message dicts, as built above
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


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The backend-neutral conversation (commons/application/ports.py) in the Messages API's shape."""
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
    return wire


def _openai_messages(system: list[str], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The backend-neutral conversation in the OpenAI-compatible shape LM Studio takes (system blocks joined)."""
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
    return wire


# ── LM Studio ──────────────────────────────────────────────────
class LMStudioBackend:
    """LM Studio's OpenAI-compatible server. Start it with `lms server start` and load a model
    first (`lms load <model>`); check memory before you do (see the resource guardrails)."""

    name = "lmstudio"
    real = False

    def __init__(self, base_url: str = "http://localhost:1234/v1", price_as: str = "claude-haiku-4-5",
                 timeout: float = 180.0, post: Callable[[dict[str, Any]], tuple[dict[str, Any], int]] | None = None,
                 tool_capable: dict[str, bool] | None = None):
        """`post` replaces the HTTP call and `tool_capable` answers `supports_tools` without asking (both for tests)."""
        self.base_url, self.price_as, self.timeout = base_url.rstrip("/"), price_as, timeout
        self._post = self._within_deadline(post or self._http_post)
        self._tool_capable: dict[str, bool] = dict(tool_capable or {})
        self._recent: deque[str] = deque(maxlen=4)  # the last prompts, one per server slot (LM Studio's default 4)
        self._recent_lock = threading.Lock()

    def supports_tools(self, model: str) -> bool:
        """LM Studio silently drops `tools` for models it doesn't mark tool-capable; the model then
        writes a plan as prose and nothing happens (found in the first local smoke run). Ask once."""
        if model not in self._tool_capable:
            root = self.base_url.rsplit("/v1", 1)[0]
            try:
                with urllib.request.urlopen(f"{root}/api/v0/models/{urllib.parse.quote(model, safe='')}", timeout=5) as r:
                    info = json.load(r)
                self._tool_capable[model] = "tool_use" in (info.get("capabilities") or [])
            except (OSError, ValueError):
                return True  # can't tell (older LM Studio): let the call go ahead
        return self._tool_capable[model]

    def structured(self, *, model, system, prompt, schema, max_tokens=1024) -> Completion:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}},
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        r, ms = self._post(body)
        usage = self._usage(r, body)
        try:
            choice = r["choices"][0]
            text = choice["message"]["content"] or ""
            if choice.get("finish_reason") == "length":
                raise ModelError("the model ran out of tokens")
            data = json.loads(text)
        except (KeyError, IndexError, ValueError) as e:
            raise ModelError(f"unusable answer from LM Studio: {str(r)[:200]}") from e
        return Completion(_check(data, schema), usage, r.get("model", model), self.price_as, False, ms, text)

    def chat(self, *, model, system, messages, tools=None, max_tokens=4096, reasoning=True) -> Turn:
        if tools and not self.supports_tools(model):
            raise ModelError(f"LM Studio doesn't give {model} tool use, so it can't act. Load a tool-capable model "
                             f"(`curl localhost:1234/api/v0/models` lists capabilities)")
        body: dict[str, Any] = {"model": model, "messages": _openai_messages(system, messages), "max_tokens": max_tokens,
                                "temperature": 0.3}
        if not reasoning:
            # Tested 26 Sep on Qwen 3.5 35B-A3B: only reasoning_effort "none" works. "/no_think",
            # chat_template_kwargs and reasoning_effort "low" all still reason until the allowance runs out.
            body["reasoning_effort"] = "none"
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        r, ms = self._post(body)
        return self._turn(r, model, ms, self._usage(r, body))

    def _usage(self, r: dict[str, Any], body: dict[str, Any]) -> Usage:
        """Tokens used, with the prompt's cached share priced as a cache read. llama.cpp keeps each slot's last prompt
        and reuses the longest common prefix (LM Studio's log: "selected slot by LCP similarity"), but doesn't report it,
        so the share is estimated the same way: the longest prefix this prompt shares with one of the last few. Without
        it, a local run charged every round of a turn in full for the conversation so far, which a cached API wouldn't."""
        u = r.get("usage") or {}
        total, out = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        prompt = json.dumps([body.get("tools"), body.get("response_format"), body["messages"]], sort_keys=True)
        with self._recent_lock:
            shared = max((len(os.path.commonprefix([prompt, p])) for p in self._recent), default=0)
            self._recent.append(prompt)
        reported = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        cached = min(total, reported if reported is not None else total * shared // max(1, len(prompt)))
        return Usage(input_tokens=total - cached, output_tokens=out, cache_read_input_tokens=cached)

    def _turn(self, r: dict[str, Any], model: str, ms: int, usage: Usage) -> Turn:
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
        if msg.get("reasoning_content") and not (msg.get("content") or "").strip() and not calls:
            stop = "max_tokens"  # it spent the whole allowance reasoning and never answered
        if calls:
            stop = "tool_use"
        return Turn(msg.get("content") or "", tuple(calls), stop, usage, r.get("model", model), self.price_as, False, ms)

    def _within_deadline(self, post: Callable[[dict[str, Any]], tuple[dict[str, Any], int]]):
        """A hard limit on each call, whatever the socket does. On 1 Oct the engine stalled mid-prompt and every call
        waited about 1,000s for LM Studio's own 600s timeout, though the socket's was 180s. The abandoned call
        finishes or fails on its own thread."""
        def call(body):
            box: dict[str, Any] = {}

            def run():
                try:
                    box["result"] = post(body)
                except Exception as e:  # handed back to the caller below
                    box["error"] = e

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            worker.join(self.timeout)
            if worker.is_alive():
                raise ModelError(f"no answer from LM Studio in {self.timeout:.0f}s; the engine may be stuck "
                                 "(reload the model: lms unload --all, then lms load)")
            if "error" in box:
                raise box["error"]
            return box["result"]

        return call

    def _http_post(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
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
    reasoning: list[bool] = field(default_factory=list)

    def structured(self, *, model, system, prompt, schema, max_tokens=1024) -> Completion:
        self.calls.append((system, prompt))
        if self.respond is None:
            raise ModelError("this fake backend has no structured answers")
        data = self.respond(system, prompt, schema)
        if isinstance(data, Exception):
            raise data
        text = json.dumps(data)
        usage = Usage(input_tokens=(len(system) + len(prompt)) // 4, output_tokens=len(text) // 4)
        return Completion(_check(data, schema), usage, model, self.price_as, self.real, 1, text)

    def chat(self, *, model, system, messages, tools=None, max_tokens=4096, reasoning=True) -> Turn:
        self.chats.append((system, messages, tools))
        self.reasoning.append(reasoning)
        if self.converse is None:
            raise ModelError("this fake backend can't chat")
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


# ── choosing a backend (every command does it the same way) ────
BACKENDS = ("fake", "lmstudio", "anthropic")


class BackendChoiceError(ValueError):
    """The command line asked for a backend it can't have: real spend not confirmed, or no local model named."""


def add_backend_args(ap, model_help: str = "model id (LM Studio: the loaded model's id)") -> None:
    ap.add_argument("--backend", choices=BACKENDS, default="fake")
    ap.add_argument("--model", help=model_help)
    ap.add_argument("--yes-spend", action="store_true", help="required for the anthropic backend: it costs real money")


def choose_backend(kind: str, model: str | None, yes_spend: bool, *, default_model: str,
                   fake: Callable[[], ModelBackend], cost: str = "") -> tuple[ModelBackend, str]:
    """(backend, model). Real money needs `yes_spend`; LM Studio needs the loaded model's id; fake needs nothing."""
    if kind == "anthropic":
        if not yes_spend:
            raise BackendChoiceError(f"The anthropic backend spends real money{f' ({cost})' if cost else ''}. "
                                     "Re-run with --yes-spend.")
        return AnthropicBackend(), model or default_model
    if kind == "lmstudio":
        if not model:
            raise BackendChoiceError("Pass --model with the id of the model loaded in LM Studio (see `lms ps`).")
        return LMStudioBackend(), model
    return fake(), "fake"


__all__ = ["AnthropicBackend", "LMStudioBackend", "FakeBackend", "BACKENDS", "BackendChoiceError", "add_backend_args",
           "choose_backend", "Completion", "ModelBackend", "ModelError", "ToolCall", "ToolResult", "Turn"]
