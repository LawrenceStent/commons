# Findings: building on earlier runs (plan, 12 Oct)

Every OSINT run so far started from nothing: the same five questions, the same searches, the same pages read again,
and answers that were written out (`answers/`) but never read back. The goal: **each run builds on what earlier runs
established**, so a question's answer gets better and more current over time instead of being redone.

## What carries over today

| Knowledge | Today | After this plan |
|---|---|---|
| Web pages read | **Never kept** until 12 Oct: an empty archive folder was swapped for a throwaway one (fixed, `3e691de`). Now kept in `archive/web/` | kept, with the date read, so stale pages can be re-read |
| Answers | written to `answers/` as reports; never read back | folded into a **dossier per question**, searchable by the co-ops |
| Findings (individual claims) | nowhere | `findings/` : each cited claim, with its sources and whether it was verified |
| Questions | the same five posted every run | a lifecycle: open, answered, due for a refresh; jobs ask for what's new |
| Lessons (why work failed) | in a report, if at all | in the dossier: "a citation typo", "attributed a fine to the wrong company" |
| Playbooks co-ops publish | memory only, lost at the end of a run | kept in the society's `playbooks/` |

`commons tick` (one saved society, cycle after cycle) already gives continuity *within* a society. Findings give it
*across* separate runs, resets and new co-ops, and they're plain files you can read and edit.

## Design

### 1. A dossier per question

Each question gets a stable id (`Q-` and a short hash of its text) and a dossier, `findings/Q-xxxx.md`:

- the **current best answer**: the latest paid answer, its date and its check (`Supported: 7 of 8`)
- **verified findings**: each cited claim from paid work, with its sources (title, link, passage) and when it was
  first and last confirmed
- **unverified and contradicted findings**: from failed work, marked, never presented as fact
- **open gaps**: the Gaps and Unknowns sections, deduplicated across runs
- **lessons**: the grader's reasons when work failed
- **history**: one line per run (date, outcome, link to the report)

A dossier is written by rule, not by a model: claims are the cited sentences of the graded parts, statuses come from
grading and the checker's tally. You can edit or delete any of it: it's a Markdown file.

### 2. Findings the co-ops can search

Dossiers live in the archive (`archive/findings/`), so `search_archive` finds them beside the pages they cite. The
rule that keeps this honest: **a finding is never a source.** Work must still cite the original passages (they're
kept now), and the grader still checks claims against those passages, so a wrong finding can't launder itself into a
new answer.

### 3. Jobs that build on the dossier

When the board posts a question that has a dossier, the job asks for an **update**, not a fresh answer:

> Prior answer (verified, 11 Oct): … Open gaps: per-company spill counts for 2025. Find what has changed since 11 Oct
> and close the gaps; reuse verified findings (cite their sources), don't search for them again.

The steward's view gains one line per job: `PRIOR FINDINGS: 9 verified, 2 contradicted, 3 open gaps (search_archive
"Q-3f2a")`.

### 4. A question lifecycle

`questions.md` stays yours. Beside it, `findings/questions.json` tracks each question's state:

- **open**: never answered; posted first
- **answered**: a verified answer exists; posted again only when a refresh is due
- **refresh due**: after a set time (say 30 days), or when a cited source has a newer version (the EA's next year of data)

Gaps can become **follow-up questions**: a co-op proposes one, and it comes to you at the gate. OSINT subjects stay
yours to choose.

### 5. Paying for updates

Re-confirming a verified answer shouldn't be paid like finding it. An update job's value scales with what it **adds**:
new verified claims, closed gaps, corrections of earlier findings. Reconfirming alone earns a small fee.

### 6. Staleness

Archive pages record when they were read. A refresh re-reads the primary sources a dossier relies on and notes what
changed. A finding whose source has changed is marked "to re-check".

## Stages

Each stage: tests, the full suite and the golden master pass, then a commit.

- [x] **F0** Pages read from the web are kept between runs (the archive fix, 12 Oct)
- [x] **L1** The changelog: per-society daily logs of every action, gzipped when the day ends, and `commons log`.
      Done when: two runs of one society land in one log you can filter by co-op and cycle
- [ ] **F1** Question ids and dossiers. Done when: after a run, `findings/Q-xxxx.md` holds each graded question's
      answer, history and lessons, rebuilt from scratch identically (writing is deterministic)
- [ ] **F2** Findings: cited claims extracted with their sources and status (`findings/findings.jsonl`); contradicted
      claims from the checker's verdicts; gaps collected; dossiers indexed in the archive. Done when:
      `search_archive` finds an earlier run's verified finding and its source
- [ ] **F3** Update jobs: a question with a dossier is posted as an update (prior answer, gaps, "what's new since");
      the steward's view shows prior findings. Done when: a second run on the same question cites the first run's
      sources without fetching them again, and its report says what changed
- [ ] **F4** Question lifecycle and refresh; follow-up questions proposed through the gate. Done when: answered
      questions wait until a refresh is due and open ones are posted first
- [ ] **F5** Pay updates by what they add; keep published playbooks between runs
- [ ] **F6** Measure it: pages fetched again, cycles to a paid answer per question, verified findings over time,
      your ratings; a knowledge panel on the dashboard

F1-F3 deliver the main benefit: the next run starts from the last one's verified findings. F4-F6 make it a lasting
research process.

## Your decisions (12 Oct)

1. **Failed answers go in dossiers**, marked NOT VERIFIED, with the grader's reasons as lessons.
2. **Refresh after 30 days.**
3. **Co-ops may propose follow-up questions** from gaps; each comes to you at the gate.
4. **Updates are paid by what they add.**
5. **A changelog**: every action by every co-op, in every run, kept as a plain debug log (below).

## The changelog (L1)

One append-only log per society, `societies/<name>/logs/<date>.jsonl`: every action, decision and change from the
activity log, with the run, cycle, co-op, actor, what happened and why, in every run, in order. A day's file is gzipped
once the day is over, so it stays small on disk; nothing is held in memory beyond the activity log's bounded window.
`commons log NAME` reads it back, filtered by co-op, cycle, run, action or text. Long texts (drafts, results) are cut
to a fixed length: the full text of finished work is in the reports and dossiers.

## Risks

- **A wrong finding repeated.** Findings are never sources, and claims are always checked against the original
  passages, so a mistake can't be cited into truth. Contradicted findings are kept and shown as contradicted.
- **Stale answers.** Every finding carries its dates; refreshes re-read the sources.
- **Prompt growth.** Dossiers are searched on demand, not pasted into every prompt; the view gets one summary line.
- **Your control.** Dossiers are plain Markdown under `societies/<name>/findings/`: read, edit or delete them; the
  next run uses what's there.
