"""Grounding: every figure in a cited claim must be in the passage it cites (12 Oct).

The first long OSINT runs failed three answers at grading for the same reason: a figure or date that wasn't in the
source cited for it ("January 2025" cited to a passage without it; a March date where the source said May; spill counts
in no source). This check finds that before the work is handed in, by rule, with no model: for each sentence that cites
the archive, the hard facts in it (money, percentages, dated months, years, and other figures) must appear in the
union of the passages it cites. It's the self-check a careful writer does, made a rule.

Adapted from the numeric consistency checker in the fwx project (forge_engine/metrics/numeric_consistency.py, and the
verifier app built on it): scale-aware amounts, so £1.2m, £1,200,000 and £1,200k are one figure, and a small tolerance
for rounding. Small whole numbers (counts like "three sources") aren't checked: words and counts are the grader's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from commons.domain.archive import citations

_CITE = re.compile(r"\[archive:[^\]]*\]", re.IGNORECASE)
_SCALE = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000, "bn": 1_000_000_000,
          "billion": 1_000_000_000}
_MONEY = re.compile(r"[£$€]\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|bn|m|k)?\b", re.IGNORECASE)
_SCALED = re.compile(r"(?<![£$€\d.,])(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand)\b", re.IGNORECASE)
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?(?:%|per ?cent\b)", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"), 1)}
_MONTH = re.compile(r"\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
                    r"\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?((?:19|20)\d{2})\b", re.IGNORECASE)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.]((?:19|20)\d{2})\b")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_SPAN = re.compile(r"\b((?:19|20)\d{2})\s*[-/–]\s*(\d{2})\b")  # 2023-24, 2023/24: a span covering both years
_NUMBER = re.compile(r"(?<![\w.,£$€])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})(?![\w%]|\s?per ?cent)")
_LEADER = re.compile(r"^\s*(?:\d+[.)]|[-*•]|claim\s+\d+:?)\s*", re.IGNORECASE)  # "1." "- " "Claim 3:" aren't facts
_TOLERANCE = Decimal("0.005")  # half a percent: rounding, not a different figure


@dataclass(frozen=True)
class Fact:
    kind: str  # money | percent | month | year | number
    value: object
    shown: str  # as written in the claim


@dataclass(frozen=True)
class Ungrounded:
    sentence: str
    fact: str
    cites: tuple[str, ...]


def _dec(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def facts(text: str) -> list[Fact]:
    """The hard facts in a text: money (in whole units, scale applied), percentages, dated months, years, figures."""
    text = _CITE.sub(" ", text or "")
    out: list[Fact] = []
    taken: list[tuple[int, int]] = []

    def free(m: re.Match) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in taken)

    for m in _MONEY.finditer(text):
        if (v := _dec(m.group(1))) is not None:
            out.append(Fact("money", int(v * _SCALE.get((m.group(2) or "").lower(), 1)), m.group(0).strip()))
            taken.append(m.span())
    for m in _SCALED.finditer(text):
        if free(m) and (v := _dec(m.group(1))) is not None:
            out.append(Fact("money", int(v * _SCALE[m.group(2).lower()]), m.group(0).strip()))
            taken.append(m.span())
    for m in _PERCENT.finditer(text):
        if free(m) and (v := _dec(m.group(1))) is not None:
            out.append(Fact("percent", v, m.group(0).strip()))
            taken.append(m.span())
    for m in _MONTH.finditer(text):
        month = _MONTHS[m.group(2).lower()[:3]]
        out.append(Fact("month", f"{m.group(4)}-{month:02d}", m.group(0).strip()))
        taken.append(m.span())
    for m in _NUMERIC_DATE.finditer(text):
        if free(m):
            out.append(Fact("month", f"{m.group(3)}-{int(m.group(2)):02d}", m.group(0)))
            taken.append(m.span())
    for m in _SPAN.finditer(text):
        if free(m):
            taken.append(m.span())  # a span is checked as the years it covers, below
            out.append(Fact("year", int(m.group(1)), m.group(0)))
            out.append(Fact("year", int(m.group(1)[:2] + m.group(2)), m.group(0)))
    for m in _YEAR.finditer(text):
        if free(m):
            out.append(Fact("year", int(m.group(1)), m.group(1)))
            taken.append(m.span())
    for m in _NUMBER.finditer(text):
        if free(m) and (v := _dec(m.group(1))) is not None:
            out.append(Fact("number", v, m.group(1)))
    return out


def _close(a, b) -> bool:
    a, b = Decimal(a), Decimal(b)
    return a == b or (b != 0 and abs(a - b) / abs(b) <= _TOLERANCE)


def found(fact: Fact, source: list[Fact]) -> bool:
    """Whether a source states the fact: money and figures within rounding, scale-aware; months and years exactly."""
    if fact.kind == "money":
        return any(f.kind in ("money", "number") and _close(fact.value, f.value) for f in source)
    if fact.kind == "percent":
        return any(f.kind in ("percent", "number") and _close(fact.value, f.value) for f in source)
    if fact.kind == "month":
        return any(f.kind == "month" and f.value == fact.value for f in source)
    if fact.kind == "year":
        return any((f.kind == "year" and f.value == fact.value) or
                   (f.kind == "month" and str(f.value).startswith(f"{fact.value}-")) for f in source)
    return any(f.kind in ("number", "money", "percent") and _close(fact.value, f.value) for f in source)


def _sentences(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", line.strip()):
            if citations(s):
                out.append(_LEADER.sub("", s))
    return out


def ungrounded(text: str, passages: dict[str, str]) -> list[Ungrounded]:
    """The figures and dates in cited sentences that none of the passages they cite state."""
    cache: dict[str, list[Fact]] = {}
    out = []
    for sentence in _sentences(text):
        cited = tuple(c for c in citations(sentence) if c in passages)
        if not cited:
            continue  # citations to nothing are another rule's business (they're refused before this)
        source = [f for c in cited for f in cache.setdefault(c, facts(passages[c]))]
        for fact in facts(sentence):
            if not found(fact, source):
                out.append(Ungrounded(" ".join(_CITE.sub("", sentence).split())[:160], fact.shown, cited))
    return out
