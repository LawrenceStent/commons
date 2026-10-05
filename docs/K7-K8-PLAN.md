# K7, K8 and R13

Your order (5 Oct): K7 (the OSINT pack), then K8 (many societies), then R13 (type checking), then Phase 2. Same
rules as before: test first; commit after each item with the full suite and the golden master green; push after
each stage; the golden master moves only where an item says so.

## K7. The OSINT pack

Investigations from public sources, about organisations, events, infrastructure and public records. Never about
private individuals. Done when (FRAMEWORK.md §9): a red-team test shows a brief targeting a private individual is
refused at founding, and a tool call aimed at one is blocked.

**Scope (my default; FRAMEWORK §12 left it open, so change it if you want):** subjects are organisations, public
bodies, events, infrastructure and public records. Sources are read only: Wikipedia and a few official registers
(for example UK Companies House and the US SEC's EDGAR), all on the allowlist, every read behind the gate.

**Design:**
- **Kernel: a pack's screen.** `Pack.screen(kind, text)` is a rule a pack can impose on what enters its society: a
  brief or question at founding, every web search and fetch before the gate sees it, and every piece of work at
  hand-in. A refusal is logged as a screened attempt; with `Pack.halt_on_screen`, the society also halts until you
  reset it (FRAMEWORK §5b: any ethics violation pauses the society). The kernel knows only "a screen".
- **Kernel: independent parts.** A part can require someone other than the job's prime: it can't be done with
  `do_part`, only bought by contract, and the contractor can't have done another part of the same job. OSINT's
  `verify` is one, so the author never checks its own citations.
- **The screen (rules, not a model's judgement):** a question or brief must name its subject's kind
  (`[org]`, `[event]`, `[infrastructure]`, `[record]`), and `[person]` is refused. Requests for personal data are
  refused wherever they appear: home addresses, phone numbers, personal email addresses, dates of birth, family
  members, where someone lives or is, and searches of people-finder sites. Work that contains personal data
  (phone numbers, personal email addresses, street addresses) is refused at hand-in.
- **The pack:** capabilities collect, verify, analyse, report; investigation questions as work; a grant economy;
  rubrics that are sourcing-first (every claim cites a source; confidence stated); a grader calibration set; a
  scorecard (citation validity, verified jobs, cost per verified job, screened attempts with a floor of zero).

### Stages
- [x] K7.1 `Pack.screen` and `Pack.halt_on_screen`: founding, web requests and hand-ins; screened attempts logged
- [x] K7.2 Independent parts: refused by `do_part`; a contractor who did another part of the job can't bid
- [x] K7.3 The OSINT screen, with red-team tests (the done-when)
- [x] K7.4 The pack: brief, work, rubrics, grant economy, populations, scorecard, calibration cases; golden runs
- [x] K7.5 A fake-model dry run end to end (the live-fake-osint golden run); docs. Also: an independent part is
      announced only once the others are done, and its contract carries their work; paid-work records keep the
      spec the doer worked from, and whole texts (they had been cut at 4,000 characters)

## K8. Many societies

Done when (FRAMEWORK.md §9): two societies run on alternate schedules on one machine, within the guardrails.

**Design:**
- **Registry:** every society is a folder: `societies/NAME` (founded) or `runs/ticks/NAME` (ticked).
  `commons list` shows each one's pack, cycle, last tick, whether it's paused, and its real spend.
- **Pause and resume:** `commons pause NAME` and `commons resume NAME` write and remove a `paused` file, which ticks
  respect.
- **Spend caps:** a real-dollar cap per society (it exists: the meter's ceiling) and one across every society, kept
  in a shared file of real spend per day, which a tick checks before it starts.
- **Scheduler:** `scripts/tick-all.sh` ticks every unpaused society in turn, one at a time, under the same lock
  and memory checks, loading the model once for all of them. The launchd file runs it instead of a single society.
- **Dashboard picker:** the dashboard can open any saved society to look at (read only), chosen from a list.

### Stages
- [x] K8.1 `commons list`; `commons pause` and `commons resume`; ticks skip a paused society
- [x] K8.2 A total real-dollar cap across societies, checked before every tick
- [x] K8.3 `scripts/tick-all.sh`: every unpaused society in turn, one model load; the launchd file uses it
- [x] K8.4 The dashboard opens a saved society, picked from the registry
- [x] K8.5 Done-when: two societies (trading and OSINT, with fake models) take turns on their own schedules
      (`commons pace`), with a paused one skipped, the cap across societies and the lock holding
      (tests/acceptance/test_many_societies.py); docs

## R13. Type checking

`pyright` in basic mode reported 247 errors on 1 Oct, mostly `None` handling and loosely typed dicts.

- [x] R13.1 pyright in the dev dependencies with its configuration: 446 errors on 5 Oct (the code had grown)
- [x] R13.2 Fixed, to zero. Most came from four things: the settings groups (built by make_dataclass, so invisible
      to a checker: now explicit classes, with a test that keeps them in step with the flat settings); `Micros` and
      the ids as NewTypes (now type aliases: money arithmetic and tool-call strings would have needed a wrapper at
      every step); event subscribers' return types (now covariant); and the runtime hooks the LLM agent uses (now a
      `RuntimeAPI` protocol). The rest were real gaps in `None` handling, fixed where they arise (`Contract.contractor`
      and `.work`, `MarketJob.owner`, guards on optional web, robots and archive results), plus read-only protocols
      for economies and the web, and positional-only desk methods. Behaviour unchanged: golden master identical
- [x] R13.3 `tests/architecture/test_types.py` runs pyright (about 2.5 seconds); a new error fails the suite
