"""Verification that decides payment (6 Oct): a job's checker part (an independent part, commons/domain/market.py)
ends with a tally, `Supported: N of M. Contradicted: K.`, which a format can require (Format.tally). Before a job is
paid, the board reads it: any claim contradicted by its source fails the job; a supported share below the pass mark
fails it too; otherwise pay scales with the share supported. So checking has teeth: a wrong answer isn't paid as if
it were right. Scripted stand-ins carry no tally and are paid as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TALLY = re.compile(r"Supported:\s*(\d+)\s*(?:of|/)\s*(\d+)\.?\s*Contradicted:\s*(\d+)", re.I)
LINE = "Supported: N of M. Contradicted: K."


@dataclass(frozen=True)
class Tally:
    supported: int
    total: int
    contradicted: int

    @property
    def share(self) -> float:
        return self.supported / self.total if self.total else 1.0


def read_tally(text: str | None) -> Tally | None:
    """The last tally in a checker's work, or None. A tally that can't be true (more supported than checked) is None."""
    found = TALLY.findall(text or "")
    if not found:
        return None
    supported, total, contradicted = (int(x) for x in found[-1])
    return Tally(supported, total, contradicted) if supported + contradicted <= total else None


def verdict(t: Tally, pass_score: float) -> str | None:
    """Why a checked job fails, or None."""
    if t.contradicted:
        return f"the check found {t.contradicted} claim(s) contradicted by their sources"
    if t.share < pass_score:
        return f"the check found only {t.supported} of {t.total} claims supported by their sources"
    return None
