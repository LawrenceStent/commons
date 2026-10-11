"""Answers: every finished job written out as a report you can read, Markdown and PDF (your decision, 11 Oct).

In a live run (`commons run` or `commons tick` with a real model), when a job is paid or fails its report goes to
`answers/<run>/` in the society's folder (beside `runs/`, or beside `state/` for a ticked society): `J2-<question>.md` and `.pdf`, and a `README.md` index of the run's answers. A failed
job is written too, marked NOT VERIFIED with the reasons, since a mostly right answer with one flagged error is worth
reading. Dry runs (the fake backend), simulations and tests write nothing.

A report: the question and its status; the answer (report part), analysis, sources gathered and the independent check
(each part's own text, as handed in); the sources, each citation `[archive: id]` turned into a numbered reference with
its page title and link; the grades with the grader's reasons; and who made each part, and how.

The PDF is typeset with Typst in-process. The words never enter the markup: the template reads them as data, so
nothing a model wrote can become Typst code. The order of the parts and their headings are the pack's
(`Pack.report_parts`); without them, parts come in the job's order under their own names.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from commons.domain import events as ev
from commons.domain.archive import citations
from commons.domain.verification import read_tally

if TYPE_CHECKING:
    from commons.application.society import World
    from commons.domain.market import MarketJob

_CITE = re.compile(r"\[archive:\s*([A-Za-z0-9-]+#\d+)\s*\]", re.IGNORECASE)
_SOURCE = re.compile(r"^Source:\s*(\S+)", re.MULTILINE)
_LABEL = re.compile(r"^[A-Z][A-Za-z ]{0,30}:?$")  # a section's label on its own line ("Findings", "Confidence:")


def blocks(text: str) -> list[list[dict]]:
    """A part's text as paragraphs of lines, each line marked if it's a section label: the PDF keeps both."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        lines = [" ".join(line.split()) for line in para.splitlines() if line.strip()]
        if lines:
            out.append([{"text": line, "label": bool(_LABEL.match(line))} for line in lines])
    return out


def folder_for(ledger_path: str) -> Path | None:
    """Where a run's answers go: `answers/<run>/` in the society's folder, or None for a ledger kept in memory."""
    if ledger_path == ":memory:":
        return None
    ledger = Path(ledger_path)
    home = ledger.parent.parent if ledger.parent.name in ("runs", "state") else ledger.parent
    return home / "answers" / ledger.stem


def slug(text: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].rstrip("-") or "answer"


@dataclass
class Source:
    number: int
    stem: str
    title: str
    url: str
    passages: list[str] = field(default_factory=list)


@dataclass
class Answers:
    """Listens to the world's events (commons/application/events.py) and writes a report for each finished job."""
    w: World
    folder: Path
    reasons: dict[str, dict[str, tuple[float, str]]] = field(default_factory=dict)  # job -> part -> (score, reason)
    written: dict[str, dict] = field(default_factory=dict)  # job -> its index row

    def observe(self, event: ev.Event) -> None:
        if isinstance(event, ev.PartGraded) and event.audit is None:
            self.reasons.setdefault(event.job, {})[event.part] = (event.grade.score, event.grade.reason)
        elif isinstance(event, ev.JobPaid):
            self.write(event.job, paid=True, why="")
        elif isinstance(event, ev.JobFailed) and any(p.artifact for p in event.job.parts.values()):
            self.write(event.job, paid=False, why=event.why)  # a job that expired with nothing written has no answer

    # ── the report ─────────────────────────────────────────────
    def write(self, job: MarketJob, *, paid: bool, why: str) -> Path:
        report = self.build(job, paid=paid, why=why)
        self.folder.mkdir(parents=True, exist_ok=True)
        name = f"{job.id}-{slug(job.title)}"
        md = self.folder / f"{name}.md"
        md.write_text(markdown(report))
        try:
            (self.folder / f"{name}.pdf").write_bytes(pdf(report))
        except Exception as e:  # a PDF that won't typeset mustn't stop the society; the Markdown is the record
            (self.folder / f"{name}.pdf-failed.txt").write_text(f"The PDF couldn't be typeset: {e}\n")
        self.written[job.id] = {"id": job.id, "title": job.title, "status": report["status_short"], "file": md.name}
        (self.folder / "README.md").write_text(index(self.folder.name, list(self.written.values())))
        return md

    def build(self, job: MarketJob, *, paid: bool, why: str) -> dict:
        sources: dict[str, Source] = {}

        def cite(text: str) -> str:
            def number(m: re.Match) -> str:
                pid = m.group(1).lower()
                stem = pid.split("#", 1)[0]
                if stem not in sources:
                    title, url = self._origin(stem)
                    sources[stem] = Source(len(sources) + 1, stem, title, url)
                s = sources[stem]
                if (n := pid.split("#", 1)[1]) not in s.passages:
                    s.passages.append(n)
                return f"[{s.number}]"
            return _CITE.sub(number, text or "").strip()

        done_by = job.done_by(self.w.contracts)
        headings = dict(self.w.pack.report_parts)
        order = [c for c, _ in self.w.pack.report_parts]
        parts = []
        for cap in sorted(job.parts, key=lambda c: order.index(c) if c in order else len(order)):
            part = job.parts[cap]
            contract = self.w.contracts.get(part.source) if part.source not in (None, "self") else None
            how = (f"bought from {contract.winner} on contract {contract.id} for {contract.price:,} credits"
                   if contract and contract.winner else "its own work" if part.source == "self" else "not handed in")
            if contract and "by default" in (contract.reason or ""):
                how += f" (NOT GRADED: {contract.reason})"
            parts.append({"capability": cap, "heading": headings.get(cap, cap.title()),
                          "text": cite(part.artifact) if part.artifact else "",
                          "by": done_by.get(cap, job.prime if part.source == "self" else "") or "", "how": how,
                          "grade": self.reasons.get(job.id, {}).get(cap)})
        check = next((p for p in job.parts.values() if p.independent and p.artifact), None)
        tally = read_tally(check.artifact) if check else None
        if paid:
            status = "Paid" + (f" · verified: {tally.supported} of {tally.total} claims supported, "
                               f"{tally.contradicted} contradicted" if tally else "")
            short = "paid"
        else:
            status = f"NOT VERIFIED · failed: {why}"
            short = "failed"
        return {"id": job.id, "title": job.title, "status": status, "status_short": short, "prime": job.prime or "",
                "cycle": self.w.cycle, "parts": parts,
                "sources": [{"number": s.number, "title": s.title, "url": s.url, "passages": sorted(s.passages, key=int)}
                            for s in sorted(sources.values(), key=lambda s: s.number)]}

    def _origin(self, stem: str) -> tuple[str, str]:
        """A cited source's title and link, from the first passage the archive keeps for it (`# title`, `Source: url`)."""
        first = self.w.archive.get(f"{stem}#1") if self.w.archive is not None else None
        text = first.text if first else ""
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), "")
        url = m.group(1) if (m := _SOURCE.search(text)) else ""
        return title or (first.source if first else stem), url


# ── formats ────────────────────────────────────────────────────
def markdown(r: dict) -> str:
    out = [f"# {r['id']} · {r['title']}", "", f"**{r['status']}**", "",
           f"Prime: {r['prime']} · finished in cycle {r['cycle']}", ""]
    for p in r["parts"]:
        if p["text"]:
            body = "\n\n".join("  \n".join(f"**{line['text'].rstrip(':')}**" if line["label"] else line["text"]
                                            for line in para) for para in blocks(p["text"]))
            out += [f"## {p['heading']}", "", body, ""]
    if r["sources"]:
        out += ["## Sources", ""]
        for s in r["sources"]:
            name = f"[{s['title']}]({s['url']})" if s["url"] else s["title"]
            out.append(f"{s['number']}. {name} (passages {', '.join('#' + n for n in s['passages'])})")
        out.append("")
    graded = [p for p in r["parts"] if p["grade"]]
    out += ["## Grades", ""]
    out += (["| Part | Score | The grader's reason |", "|---|---|---|"]
            + [f"| {p['capability']} | {p['grade'][0]:.2f} | {' '.join(p['grade'][1].split()).replace('|', '/')} |"
               for p in graded] if graded else ["No part was graded (the job ended before grading)."])
    out += ["", "## How it was made", "", "| Part | Done by | How |", "|---|---|---|"]
    out += [f"| {p['capability']} | {p['by'] or '-'} | {p['how']} |" for p in r["parts"]]
    return "\n".join(out) + "\n"


def index(run: str, rows: list[dict]) -> str:
    out = [f"# Answers from {run}", "", f"{sum(r['status'] == 'paid' for r in rows)} paid, "
           f"{sum(r['status'] == 'failed' for r in rows)} failed (not verified). Each has a Markdown and a PDF copy.", "",
           "| Job | Question | Status |", "|---|---|---|"]
    out += [f"| {r['id']} | [{r['title']}]({r['file']}) | {r['status']} |" for r in rows]
    return "\n".join(out) + "\n"


PDF_TEMPLATE = """
#let d = json("data.json")
#set document(title: d.title)
#set page(paper: "a4", margin: (x: 2.2cm, y: 2cm),
  footer: context [#set text(size: 8pt, fill: luma(110)); #d.id #h(1fr) #counter(page).display()])
#set text(font: "Libertinus Serif", size: 10.5pt, lang: "en")
#set par(justify: true, leading: 0.65em, spacing: 0.9em)
#show heading: set text(fill: rgb("#20345c"))

#text(size: 17pt, weight: "bold")[#d.id · #d.title]
#v(0.3em)
#block(fill: if d.paid { rgb("#e8f2e8") } else { rgb("#fbe9e7") }, inset: 7pt, radius: 3pt, width: 100%)[
  #text(weight: "bold")[#d.status]]
#text(size: 9pt, fill: luma(90))[Prime: #d.prime · finished in cycle #d.cycle]

#for p in d.parts {
  if p.text != "" {
    heading(level: 2, p.heading)
    for para in p.paragraphs {
      par(para.map(l => if l.label { strong(l.text) } else { l.text }).join(linebreak()))
    }
  }
}

#if d.sources.len() > 0 {
  heading(level: 2, "Sources")
  for s in d.sources {
    block[#s.number. #s.title #if s.url != "" { linebreak(); text(size: 8.5pt, link(s.url, s.url)) }]
  }
}

#heading(level: 2, "Grades")
#if d.grades.len() > 0 {
  table(columns: (auto, auto, 1fr), stroke: 0.4pt + luma(180), inset: 5pt,
    [*Part*], [*Score*], [*The grader's reason*],
    ..d.grades.map(g => (g.part, g.score, g.reason)).flatten())
} else [No part was graded (the job ended before grading).]

#heading(level: 2, "How it was made")
#table(columns: (auto, auto, 1fr), stroke: 0.4pt + luma(180), inset: 5pt,
  [*Part*], [*Done by*], [*How*],
  ..d.parts.map(p => (p.capability, p.by, p.how)).flatten())
"""


def pdf(r: dict) -> bytes:
    import typst
    data = {"id": r["id"], "title": r["title"], "status": r["status"], "paid": r["status_short"] == "paid",
            "prime": r["prime"], "cycle": str(r["cycle"]),
            "parts": [{"capability": p["capability"], "heading": p["heading"], "text": p["text"],
                       "paragraphs": blocks(p["text"]),
                       "by": p["by"] or "-", "how": p["how"]} for p in r["parts"]],
            "sources": [{"number": str(s["number"]), "title": s["title"], "url": s["url"]} for s in r["sources"]],
            "grades": [{"part": p["capability"], "score": f"{p['grade'][0]:.2f}", "reason": p["grade"][1]}
                       for p in r["parts"] if p["grade"]]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.typ").write_text(PDF_TEMPLATE)
        (root / "data.json").write_text(json.dumps(data))
        return typst.compile(str(root / "main.typ"), root=str(root), format="pdf")


__all__ = ["Answers", "folder_for", "markdown", "pdf", "index", "citations"]
