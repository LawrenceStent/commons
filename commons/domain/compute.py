"""Compute: token usage, the price table and what a call costs. Charging it is the meter's job (commons/substrate/meter.py)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25


PRICES: dict[str, Price] = {
    "claude-haiku-4-5": Price(1.00, 5.00, 0.10),
    "claude-sonnet-5": Price(2.00, 10.00, 0.20),
    "claude-opus-5": Price(5.00, 25.00, 0.50),
    "claude-opus-5-5": Price(4.00, 20.00, 0.20),
    # a model on this machine (LM Studio): nothing is billed, but thinking still costs the society something, so it
    # isn't free to waste. One fifth of Haiku (your decision, 11 Oct: at Haiku's price, thinking used 80% of a live
    # OSINT society's money in ten cycles, before any work could be paid)
    "local": Price(0.20, 1.00, 0.02),
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def cost_micros(model: str, usage: Usage) -> int:
    """Cost in micro-dollars. $1/Mtok == 1 micro-dollar per token."""
    p = PRICES[model]
    return round(
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_input_tokens * p.cache_read
        + usage.cache_creation_input_tokens * p.cache_write
    )

