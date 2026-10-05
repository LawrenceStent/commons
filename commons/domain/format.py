"""Formats: what a part's text must look like, checked by rule before any grader reads it.

A pack declares a format per capability (`TemplateWorkSource.formats`): a word range and the sections it must have. A
grader can miss a word count; a rule can't. In the first full tech-for-good run (2 Oct), a brief that was over its
350-word limit was handed in, then graded 0.40 and rejected. Now it is refused at hand-in, with the reason, while it
can still be fixed. Citations (`[archive: <id>]`) don't count as words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from commons.domain.archive import sources
from commons.domain.verification import LINE, read_tally

_CITATION = re.compile(r"\[archive:[^\]]*\]")
_WORD = re.compile(r"[A-Za-z0-9][\w'’-]*")


def words(text: str) -> int:
    return len(_WORD.findall(_CITATION.sub("", text)))


def has_section(text: str, name: str) -> bool:
    """A line that starts with the section's name, whatever the markup around it (## Risks, **Risks**, Risks:)."""
    return bool(re.search(rf"^\W*{re.escape(name)}\b", text, re.IGNORECASE | re.MULTILINE))


@dataclass(frozen=True)
class Format:
    min_words: int | None = None
    max_words: int | None = None
    sections: tuple[str, ...] = ()
    tally: bool = False  # a checker part: must end with "Supported: N of M. Contradicted: K." (domain/verification.py)
    min_sources: int = 0  # distinct source files cited (domain/archive.py): one page cited three times is one source

    def problems(self, text: str) -> list[str]:
        n, out = words(text), []
        if self.max_words is not None and n > self.max_words:
            out.append(f"it is {n} words; the most is {self.max_words}")
        if self.min_words is not None and n < self.min_words:
            out.append(f"it is {n} words; the least is {self.min_words}")
        if missing := [s for s in self.sections if not has_section(text, s)]:
            out.append(f"it lacks the section(s) {', '.join(missing)} (each on a line of its own, starting with its name)")
        if (n := len(sources(text))) < self.min_sources:
            out.append(f"it cites {n} different source(s); the least is {self.min_sources} (passages of one page are one "
                       f"source)")
        if self.tally and read_tally(text) is None:
            out.append(f"it doesn't end with its tally, a line like '{LINE}' (supported plus contradicted at most M)")
        return out

    def describe(self) -> str:
        """The format in a sentence, for whoever writes the part."""
        bits = []
        if self.min_words is not None or self.max_words is not None:
            bits.append(f"{self.min_words or 0} to {self.max_words} words" if self.max_words is not None
                        else f"at least {self.min_words} words")
        if self.sections:
            bits.append("sections, each on a line starting with its name: " + ", ".join(self.sections))
        if self.min_sources:
            bits.append(f"citations from at least {self.min_sources} different sources")
        if self.tally:
            bits.append(f"a closing tally line: {LINE}")
        return "; ".join(bits)
