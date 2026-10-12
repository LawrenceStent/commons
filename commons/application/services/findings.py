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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from commons.application.services.approvals import CARRIERS
from commons.domain import events as ev
from commons.domain.archive import citations

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.market import MarketJob

PREFIX = "findings"  # dossier passages' ids start with this: "findings-q-3f2a1b#2"
REFRESH_DAYS = 30  # an answered question is asked again after this long (your decision, 12 Oct)
RECONFIRM = 0.2  # what an update earns, as a share of its value, if it adds nothing new (F5)
PROPOSE = "propose_question"  # the gate tool for a follow-up question a co-op proposes
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
    proposed: dict[str, str] = field(default_factory=dict)  # question id -> a follow-up waiting for your decision

    def observe(self, event: ev.Event) -> None:
        if isinstance(event, ev.PlaybookPublished) and event.playbook.author != "operator":
            self.keep_playbook(event.playbook)
        elif isinstance(event, ev.PartGraded) and event.audit is None and event.grade.score < 0.5:
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

    # ── F6: what the society knows, across its runs ────────────
    def stats(self) -> dict[str, int]:
        """Questions with a verified answer, and verified findings, across every run's dossiers."""
        answered = verified = 0
        for path in sorted(self.folder.glob("Q-*.json")) if self.folder.exists() else []:
            outcomes = json.loads(path.read_text()).get("outcomes", [])
            paid = [o for o in outcomes if o["status"] == "paid"]
            answered += bool(paid)
            verified += len({c["text"] for o in paid for c in o["claims"] if c["status"] == "verified"})
        return {"answered": answered, "verified": verified}

    # ── F5: updates paid by what they add; playbooks kept ──────
    def novelty(self, job: MarketJob) -> float | None:
        """The share of an update's claims its question's dossier doesn't already hold as verified (corrections and new
        findings count), at least RECONFIRM. None for a question never verified: its first answer is all new."""
        state = self.load(question_id(job.title))
        known = {c["text"] for o in (state or {}).get("outcomes", []) if o["status"] == "paid"
                 for c in o["claims"] if c["status"] == "verified"}
        if not known:
            return None
        claims = [s for p in job.parts.values() if p.artifact and not p.independent for s in claims_of(p.artifact)]
        if not claims:
            return RECONFIRM
        return max(RECONFIRM, sum(c not in known for c in claims) / len(claims))

    def keep_playbook(self, playbook) -> None:
        """A playbook a co-op published joins the society's playbooks/, seeded into the library of later runs."""
        folder = self.folder.parent.parent / "playbooks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{playbook.capability}--{re.sub(r'[^a-z0-9]+', '-', playbook.title.lower()).strip('-')[:60]}.md"
        if not path.exists():
            path.write_text(f"{playbook.text.strip()}\n\n(published by {playbook.author}, run {self.run})\n")

    # ── F4: which questions are posted, and follow-ups ─────────
    def due(self, subjects, live: set[str], now: float | None = None) -> list[str]:
        """The questions to post from: open ones (never answered) first; else answered ones whose refresh is due
        (REFRESH_DAYS after their last verified answer); never one with a job already on the board. Empty when every
        question is answered and fresh: nothing is posted."""
        now = now or time.time()
        open_, stale = [], []
        for s in subjects:
            if s in live:
                continue
            state = self.load(question_id(s))
            paid = [o for o in (state or {}).get("outcomes", []) if o["status"] == "paid"]
            if not paid:
                open_.append(s)
            elif now - time.mktime(time.strptime(paid[-1]["date"], "%Y-%m-%d")) >= REFRESH_DAYS * 86_400:
                stale.append(s)
        return open_ or stale

    def questions_file(self) -> Path:
        return self.folder.parent.parent / "questions.md"  # the society's own (archive/findings -> society)

    def add_question(self, text: str) -> None:
        """A follow-up you approved joins the society's questions: its file, and the board from now on."""
        path = self.questions_file()
        existing = path.read_text() if path.exists() else ""
        path.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n") + text + "\n")
        ws: Any = self.w.pack.work_source  # a template work source has subjects; others don't take questions
        if hasattr(ws, "subjects") and text not in ws.subjects:
            self.w.pack = replace(self.w.pack, work_source=replace(ws, subjects=(*ws.subjects, text)))

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


def _approve_question(w, r) -> tuple[bool, str]:
    """You approved a follow-up question: it's added to the society's questions and posted like any other."""
    findings = w.findings
    text = findings.proposed.pop(r.target, None) if findings is not None else None
    if findings is None or text is None:
        return False, "the proposal is no longer on record"
    findings.add_question(text)
    return True, f"added to this society's questions: {text}"


CARRIERS[PROPOSE] = _approve_question
