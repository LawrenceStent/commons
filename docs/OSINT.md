# OSINT: how it works

The OSINT pack (K7, built 5 Oct; `packs/osint/`) runs societies that answer questions from public sources about
**organisations, events, infrastructure and public records**, never about private individuals. Sourcing comes
first: every claim cites a source, and a co-op that did no other part of the job checks the citations. The rules that
matter most are code, not prompts, and breaking one halts the whole society until you reset it.

## How a question becomes an answer

1. **You write the questions.** Each names its subject's kind: `[org]`, `[event]`, `[infrastructure]` or
   `[record]` (for example `[event] What happened in the 2021 Suez Canal blockage?`). A society's
   `questions.md` replaces the pack's eight defaults. The screen reads every question at founding, and again
   whenever the society loads; `[person]`, untagged questions and anything asking for personal data are refused.
2. **The board posts jobs.** Each job is one question and some of its four parts:
   - **collect**: at least three public sources, each cited `[archive: <id>]` with what it says
   - **analyse**: Findings, Confidence and Gaps (150 to 350 words), every finding cited
   - **report**: Answer, Confidence and Unknowns (200 to 400 words), every claim cited
   - **verify**: every cited claim in the others' work checked against its source: supported, contradicted or
     unverifiable, uncited claims flagged, ending with the tally `Supported: N of M. Contradicted: K.` (required by
     its format)
3. **A co-op claims a job**, by the kernel's allocation rule (most trusted, best fit, least loaded).
4. **Reading the web.** Members search and fetch through the gate. Every request passes the screen first, then
   your `[gate]` policy and allowlist, then the network layer's own allowlist. Pages read join the society's
   archive as passages that can be cited.
5. **Writing.** Members write each part from the archive. Formats are rules: wrong length or a missing section is
   refused at hand-in, with the reason, before any grader reads it. The screen reads every hand-in too, and personal
   data (phone numbers, personal email, street addresses, dates of birth) is refused.
6. **Verify comes last, from someone else.** It's an independent part: the job's own co-op can't do it, and nobody
   who did or holds another part of the job may bid on it or be awarded it. It can be announced only once the other
   parts are done, and its contract carries their work, fenced as material, for the verifier to check.
7. **Grading.** Each part is graded against its rubric by the pack's grader (calibrated on eight hand-labelled
   cases). A citation to a passage that doesn't exist fails the part by rule, before any grader reads it. The grader
   is shown the text of every passage the part cites (up to eight), and told that a claim its source doesn't
   support misses the rubric.
8. **Payment.** A job is paid when every part passes **and its check holds**: the board reads the verify tally, and
   any contradicted claim, or fewer supported than the pass mark (half), fails the job. Otherwise its value scales
   with the share supported (3 of 4 supported: 75% of the value). The society runs on grants: a fixed budget each
   cycle, shared by the work that passes, by value.

## The rules, and where each is enforced

| Rule | Where | What happens |
|---|---|---|
| Subjects are organisations, events, infrastructure or public records, never people | the screen: founding, every load | founding refused, with the reason |
| No requests for personal data, no locating or tracking people, no people-finder sites | the screen: briefs, questions, every web search and fetch | refused; **the society halts** until you reset it |
| No pages about people (register officer pages, profiles) | the screen: every fetch | refused; the society halts |
| No personal data in the work | the screen: every hand-in | refused; the society halts |
| Read only, public pages only, allowlisted hosts only, robots.txt respected | the gate (your `[gate]` policy) and the network layer, independently | refused |
| Every claim cites a real source | the citation rule at grading | a made-up citation fails the part |
| Claims say no more than their sources | the grader, shown the cited passages | an unsupported claim misses the rubric |
| A contradicted claim isn't paid | the verify tally, read by the board (`commons/domain/verification.py`) | the job fails; pay otherwise scales with the share supported |
| The checker isn't an author | independent parts (`do_part`, `bid`, `award`) | refused |
| Subjects come from you, not the co-ops | the pack leaves out ventures | not offered; refused if called |
| Formats (length, sections) | at hand-in | refused with the reason |

The screen's rules are deliberately broad (`packs/osint/screen.py`): a refused public-interest question can be
reworded; a leaked address can't be unleaked. Because a refusal halts the society, a false positive stops it too.
For example, a search like "where the grid's backup works" trips the "where … works" rule. That's the price of the
conservative setting; the log and your inbox say exactly what was refused and why.

## Setting one up

```sh
# your questions, one per line, each tagged
cat > questions.md <<'EOF'
[event] What is the public timeline of the 2024 CrowdStrike outage, and what did it disrupt?
[infrastructure] Who operates the Thames Barrier, and how often has it been closed?
EOF

uv run commons found inquiry --pack osint --brief brief.md --questions questions.md --backend lmstudio --model <id>
# read and edit societies/inquiry/blueprints.toml, then:
uv run commons found inquiry --approve
```

Then give it the web in `societies/inquiry/operator/config.toml`:

```toml
[gate]
read = "ask"        # each read waits for you; "allow" lets reads on these hosts run at once
allow_hosts = ["en.wikipedia.org", "find-and-update.company-information.service.gov.uk", "www.sec.gov"]
per_cycle = 4
```

Run it with `commons run --society inquiry` (or tick it on a schedule: `commons tick inquiry`). Decide waiting reads
with `commons approve inquiry` or on the dashboard. If the society halts on a screened attempt, read why in its
activity log, then reset the kill-switch from the dashboard. Check the grader first with
`commons calibrate --pack osint --backend lmstudio --model <id>`.

## What's measured

| Metric | Measured by | Notes |
|---|---|---|
| Screened attempts | code | must stay at zero: any refusal is a breach (and a halt) |
| Verified answers | code | paid jobs whose citations another co-op checked |
| Work citing sources | code | share of paid collect, analyse and report parts with a real citation (target 90%) |
| Thinking per verified answer | code | credits of model calls per verified answer |
| Useful answers, share rated useful | you (`commons rate`) | your ratings of a sample |
| Mean grade | grader | |
| Archive citations valid | code (kernel) | share of citations that point at real passages |

## Built against the original design (FRAMEWORK.md §7.4, §5b)

| Designed | Built? | Impact today |
|---|---|---|
| Collect, verify, analyse, report | yes | |
| Every claim cites a source | partly: a citation must point at a passage that exists | the citation can still misquote or overstate its source; only the verifier and the grader stand between that and payment |
| A verify co-op, not the author, checks citations | yes (independent parts) | the verifier's own verdicts aren't checked against the sources (see below) |
| Payment held until verification completes | **yes** (6 Oct): the verify tally decides payment | a contradicted claim fails the job; pay scales with the share supported. The verifier's tally is itself graded against the sources it cites |
| Grader scores corroboration and calibration | corroboration yes (6 Oct): the grader sees the cited passages; calibration not yet | the grader judges whether the sources say it, not only whether the writing is careful |
| Source independence measured | no | **medium-low**: an answer resting on one source cited three times can look corroborated |
| Confidence calibration (Brier score over resolved claims) | no | **low now**: most answers never "resolve" within a run; it matters once answers include predictions |
| Corrections tracked (retractions, honesty about them) | no | **low now**: matters once answers are published and later shown wrong |
| Questions answered fully, partly or not | partly: your ratings of a sample | low |
| Cost per verified *claim* | per verified *answer* | low |
| Ethics violations floor zero, any violation pauses | yes: the screen, and the halt | |
| Passive collection, site terms and robots respected | yes: reads only, allowlist, robots.txt | |
| Legal and ethical review of the brief before founding | by rule (the screen) plus your approval of blueprints | no separate legal review step; you are the reviewer |

### The two gaps that mattered, closed (6 Oct)

Both are kernel changes, so every pack gets them:

1. **Verification decides payment.** Any pack can give a part `Format(tally=True)`; an independent part's tally is
   read by the board before payment. A contradicted claim fails the job (the bond is forfeited); a supported share
   below the pass mark fails it; otherwise value scales with the share. An author's own count doesn't count: only an
   independent part's.
2. **Graders see the sources.** Every part that cites archive passages is graded with those passages beside it.

Still to do: count distinct sources per answer, confidence calibration, corrections, and cost per verified claim.
