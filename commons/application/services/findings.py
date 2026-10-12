"""Findings: what a society has established about each question, kept across runs (docs/FINDINGS-PLAN.md, F1-F2).

When a job is paid or fails, its question's record grows by one outcome: the date and run, paid or not (and why), the
answer, every cited claim with its status, the open gaps, and lessons (the grader's reasons when a part failed). The
record is `<id>.json` and a dossier rendered from it, `<id>.md`, in the society's `archive/findings/`, so the co-ops
find dossiers with `search_archive` in this run and the next, beside the pages their claims cite.

Written by rule, never by a model: claims are the cited sentences of the graded parts; a claim is verified when its job
was paid, not verified when the job failed, contradicted when the checker's own lines say so (and the job then fails).
Your decisions (12 Oct): failed answers go in, marked, with their reasons.

**A finding is never a source.** Dossiers keep their claims' original citations, so co-ops can go straight to the pages,
but work that cites a dossier passage is refused at hand-in (commands/base.py) and fails at grading
(services/grading.py): every claim is still checked against the page it came from.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.archive import citations

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.market import MarketJob

PREFIX = "findings"  # dossier passages' ids start with this: "findings-q-3f2a1b#2"
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_LABEL = re.compile(r"^\**([A-Z][A-Za-z ]{0,30}?)\**:?\s*$")


def question_id(title: str) -> str:
    """A question's stable id: the same words, the same id, in any run."""
    return "Q-" + hashlib.sha1(" ".join(title.lower().split()).encode()).hexdigest()[:6]


def is_finding(passage_id: str) -> bool:
    return passage_id.lower().startswith(PREFIX + "-")


def sections(text: str) -> dict[str, str]:
    """A part's labelled sections ("Findings", "Gaps", ...): label -> its text."""
    out, label, buf = {}, "", []
    for line in (text or "").splitlines():
        if m := _LABEL.match(line.strip()):
            if label:
                out[label] = "\n".join(buf).strip()
            label, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if label:
        out[label] = "\n".join(buf).strip()
    return out


def claims_of(text: str) -> list[str]:
    """The sentences of a text that cite the archive, whole and in order."""
    out = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        for sentence in _SENTENCE.split(para.strip()):
            if citations(sentence) and len(sentence) < 1200:
                out.append(" ".join(sentence.split()))
    return out


def contradicted_ids(checker: str) -> set[str]:
    """Passages the checker named on a line it marked contradicted (its tally line aside)."""
    out = set()
    for line in (checker or "").splitlines():
        if re.search(r"contradict", line, re.I) and not re.search(r"Supported:\s*\d", line):
            out.update(citations(line))
    return out


@dataclass
class Findings:
    """Listens to the world's events (commons/application/events.py) and keeps each question's record."""
    w: World
    folder: Path
    run: str = ""  # the run outcomes are recorded under (its ledger's name)
    reasons: dict[str, dict[str, str]] = field(default_factory=dict)  # job -> part -> why it failed grading

    def observe(self, event: ev.Event) -> None:
        if isinstance(event, ev.PartGraded) and event.audit is None and event.grade.score < 0.5:
            self.reasons.setdefault(event.job, {})[event.part] = event.grade.reason
        elif isinstance(event, ev.JobPaid):
            self.record(event.job, paid=True, why="")
        elif isinstance(event, ev.JobFailed) and any(p.artifact for p in event.job.parts.values()):
            self.record(event.job, paid=False, why=event.why)

    # ── the record ─────────────────────────────────────────────
    def record(self, job: MarketJob, *, paid: bool, why: str) -> Path:
        qid = question_id(job.title)
        state = self.load(qid) or {"id": qid, "question": job.title, "outcomes": []}
        state["outcomes"].append(self.outcome(job, paid=paid, why=why))
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{qid}.json").write_text(json.dumps(state, indent=1, ensure_ascii=False))
        md = self.folder / f"{qid}.md"
        md.write_text(dossier(state))
        if self.w.archive is not None:  # searchable at once, not only from the next run
            self.w.archive.replace_source(f"{PREFIX}/{qid}.md", md.read_text())
        return md

    def brief(self, job: MarketJob) -> bool:
        """F3: a question the society has worked on before is posted as an update. Each part's instructions open with
        what was established and when, the open gaps, and where the dossier is; the work builds on it instead of
        starting again. True if the job was briefed."""
        state = self.load(question_id(job.title))
        if not state or not state["outcomes"]:
            return False
        note = update_note(state)
        for part in job.parts.values():
            part.spec = f"{note}\n\n{part.spec}"
        return True

    def load(self, qid: str) -> dict | None:
        path = self.folder / f"{qid}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def outcome(self, job: MarketJob, *, paid: bool, why: str) -> dict:
        order = [c for c, _ in self.w.pack.report_parts] or sorted(job.parts)
        texts = {c: p.artifact for c, p in job.parts.items() if p.artifact}
        checker = next((p.artifact for p in job.parts.values() if p.independent and p.artifact), "")
        against = contradicted_ids(checker)
        claims, seen = [], set()
        for cap in sorted(texts, key=lambda c: order.index(c) if c in order else len(order)):
            if job.parts[cap].independent:
                continue  # the checker's lines are verdicts on claims, not claims
            for sentence in claims_of(texts[cap]):
                if sentence in seen:
                    continue
                seen.add(sentence)
                status = ("contradicted" if against & set(citations(sentence)) else
                          "verified" if paid else "not verified")
                claims.append({"text": sentence, "part": cap, "status": status})
        gaps = []
        for cap, text in texts.items():
            for label, body in sections(text).items():
                if label.lower() in {g.lower() for g in self.w.pack.gap_sections}:
                    gaps += [" ".join(s.split()) for s in _SENTENCE.split(body) if s.strip()]
        answer_cap = next((c for c in order if c in texts and not job.parts[c].independent), None)
        return {"date": time.strftime("%Y-%m-%d"), "run": self.run, "cycle": self.w.cycle, "job": job.id,
                "status": "paid" if paid else "failed", "why": why, "answer": texts.get(answer_cap, "") if answer_cap else "",
                "claims": claims, "gaps": list(dict.fromkeys(gaps)),
                "lessons": [f"{cap}: {reason}" for cap, reason in sorted(self.reasons.pop(job.id, {}).items())]}


# ── the update note ────────────────────────────────────────────
def update_note(state: dict) -> str:
    """What a job on a question worked before starts from: short, so it fits in every part's instructions."""
    outcomes = state["outcomes"]
    paid = [o for o in outcomes if o["status"] == "paid"]
    verified = {c["text"] for o in paid for c in o["claims"] if c["status"] == "verified"}
    contradicted = {c["text"] for o in outcomes for c in o["claims"] if c["status"] == "contradicted"}
    gaps = list(dict.fromkeys(g for o in outcomes for g in o["gaps"]))
    since = paid[-1]["date"] if paid else outcomes[-1]["date"]
    lines = [f"UPDATE: this question was worked on before ({len(outcomes)} time{'s' if len(outcomes) != 1 else ''}; "
             + (f"verified answer of {since}" if paid else f"no verified answer yet, last tried {since}") + "). "
             f"Its dossier is in the archive: search_archive \"{state['id']}\"; read it first.",
             f"- Verified findings: {len(verified)}. Reuse them by citing the pages their [archive: ...] ids point to "
             "(already in the archive: don't fetch them again). Never cite the dossier itself."]
    if contradicted:
        lines.append(f"- Contradicted findings: {len(contradicted)}. Don't repeat them.")
    if gaps:
        lines.append("- Open gaps: " + " | ".join(g[:160] for g in gaps[:3]) + (" | ..." if len(gaps) > 3 else ""))
    lines.append(f"- Say what has changed since {since}, and close gaps where the sources allow.")
    return "\n".join(lines)


# ── the dossier ────────────────────────────────────────────────
def dossier(state: dict) -> str:
    """A question's record as a dossier, deterministic: the same record, the same text."""
    outcomes = state["outcomes"]
    paid = [o for o in outcomes if o["status"] == "paid"]
    latest = paid[-1] if paid else None
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}
    status: dict[str, str] = {}
    for o in outcomes:
        for c in o["claims"]:
            first_seen.setdefault(c["text"], o["date"])
            last_seen[c["text"]] = o["date"]
            if status.get(c["text"]) != "verified" or c["status"] == "contradicted":
                status[c["text"]] = c["status"]
    head = (f"answered: verified on {latest['date']}" if latest else
            f"not yet verified ({len(outcomes)} attempt{'s' if len(outcomes) != 1 else ''})")
    out = [f"# {state['id']} · {state['question']}", "", f"Status: {head}. Findings are leads, never sources: cite the "
           "pages their [archive: ...] ids point to, after reading them.", ""]
    if latest:
        out += [f"## Current best answer ({latest['date']}, job {latest['job']})", "", latest["answer"], ""]
    groups = [("Verified findings", "verified"), ("Not verified findings", "not verified"),
              ("Contradicted findings", "contradicted")]
    for heading, kind in groups:
        rows = [t for t, s in status.items() if s == kind]
        if rows:
            out += [f"## {heading}", ""]
            out += [f"- {t} (first {first_seen[t]}, last {last_seen[t]})" for t in rows]
            out.append("")
    gaps = list(dict.fromkeys(g for o in outcomes for g in o["gaps"]))
    if gaps:
        out += ["## Open gaps", ""] + [f"- {g}" for g in gaps] + [""]
    lessons = [(o["date"], o["job"], lesson) for o in outcomes for lesson in o["lessons"]]
    if lessons:
        out += ["## Lessons", ""] + [f"- {d} {j}: {lesson}" for d, j, lesson in lessons] + [""]
    out += ["## History", "", "| Date | Run | Job | Outcome |", "|---|---|---|---|"]
    out += [f"| {o['date']} | {o['run']} | {o['job']} | {o['status']}{': ' + o['why'] if o['why'] else ''} |"
            for o in outcomes]
    return "\n".join(out) + "\n"
