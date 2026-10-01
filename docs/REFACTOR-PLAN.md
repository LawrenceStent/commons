# Refactor plan: towards Ports and Adapters, with DDD tactics and TDD

Follows from `docs/ARCHITECTURE-AUDIT.md` (finding ids such as S1 or D3 refer to it). Branch:
`refactor/architecture`, cut from `phase-1` at `85160fc`. No feature work on `phase-1` until this merges back.
Decisions are in §5; progress is the checklists in §3.

**The rule of this refactor: behaviour does not change.** Every commit passes the full test suite and a golden-master
test that pins today's runs byte for byte. Anything that would change behaviour is out of scope, or goes to you as
a separate, labelled decision.

---

## 1. Target architecture

### 1.1 The dependency rule (as built in R3)

```
  packs        plug-ins: a society's purpose (may import anything below)               outermost
  interfaces   composition roots: the commons CLI and the dashboard
  adapters     ports implemented against other processes and the network
               (model backends, the web, Redis)
  agents       what plays a co-op: scripted strategies, the LLM steward and its members
  application  the society (World), its cycle, services and commands, through ports
  substrate    in-process platform services, standard library only: ledger (SQLite), in-memory bus,
               telemetry, registry, meter, reputation, activity log, JSON-lines files, workspace
  domain       pure rules and models: statuses, jobs, grading, packs, gate policy, venture rules,
               archive index, scorecard, compute prices, blueprints, operator limits
  protocol     signed messages                                                          innermost
```

Each layer imports only layers below it; `tests/test_layers.py` checks it from the source (type-only imports count)
and has **no exceptions** since R3. Two decisions made while building it, 1 Oct:

- **Local files are platform, not adapters.** A single-process simulation reads and writes its own folders (the
  society folder, the operator folder, the archive, ratings and gate files) with the standard library, through
  `substrate`. Adapters are reserved for things in another process or across the network, which is where
  substitution, failure and cost actually matter.
- **Agents sit inside adapters.** Agents use only ports (the observation, the actions API, the model port); adapters
  may assemble them (a founded society's co-ops).

### 1.2 Package layout (as built in R3)

```
commons/
  protocol/      envelope, contract, knowledge, population, reputation
  domain/        status, compute, grading, market, pack, community, goals, scorecard, archive (index),
                 gate (policy), ventures (rules), operator (limits), ratings (scale), founding (blueprints)
  substrate/     ledger, meter, bus, registry, reputation, telemetry, activity, jsonl, workspace
  application/   ports, world, actions, population, observation, graders, calibration, gate (queue), ventures
                 (checks, LLM appraiser), archive (folder), operator (folder), ratings (files), founding (folder)
  agents/        scripted/ (base, scripted), llm/ (steward, render, tools, fakes)
  adapters/      models (Anthropic, LM Studio, fake), web (urllib), redis_bus
  interfaces/    cli/ (main, live, sim, found, approve, rate, calibrate), console/ (app, host, dashboard)
packs/           earn_online, tech_for_good
sim/             shims for the old `python -m sim.*` commands
```

Later stages refine inside these layers (R4 and R5 add aggregates and policies to `domain`; R6 splits `world.py`
into services; R10 splits `agents/llm`), and `reputation` moves from `substrate` to `domain` once R7's events
remove its telemetry calls.

### 1.3 Patterns, and where each one lands

| Pattern | Replaces | Fixes |
|---|---|---|
| **Aggregate** (`Job`, `Contract`) with a transition table; illegal moves raise `DomainError` | 60 scattered `status == "…"` checks | C2, C3 |
| **Value objects / NewTypes** (`Micros`, ids) and **StrEnum** statuses | bare ints and strings | C3 |
| **Policy (Strategy pattern)**: `PaymentPolicy` with `MarketPayment` and `GrantPayment` | 7 `economy == "grant"` checks | S4; K6's capital economy becomes a new class |
| **Domain events** plus subscribers (inbox, telemetry, activity log) | 37 `_tell`, 23 `hub.emit` and `activity.add` by hand | D7 |
| **Pipeline**: the cycle as phases | a 43-line `step()` with implicit order | S1, C8 |
| **Command + middleware** (operator limits, then lock, then log) | `setattr` loops at import | C6, S2 |
| **Ports and Adapters** for models, web, ledger, files | concrete imports and in-function imports | A1, A2, A4, S8 |
| **Composition root** per interface; one CLI with `main(argv)` | five import-time scripts | A5, S5, D2 |
| **Read models** (ObservationBuilder, dashboard queries) | `World.observe` (74 lines), `snapshot` (122) | S1, C1 |
| **Facade** (`Society` keeps today's `World` API during and after the move) | — | keeps the console, packs and tests working throughout |

---

## 2. How we work

1. **Golden master first** (R0). It runs scripted societies (seeds 0, 3 and 7, both packs, 200 cycles) and a
   fake-model live society (10 cycles, sequential), and stores, per run:
   - every ledger posting
   - every telemetry event (kind and fields, without wall-clock times)
   - every activity entry (without times)
   - every event each co-op was told
   - the summary text

   Every later commit must reproduce them exactly.
2. **After every checklist item:** run the full test suite (gated on pytest's exit code, never piped) and the
   golden master, then commit with the item named ("R1.3: …"), and tick the item in this file in the same commit.
3. **At the end of each stage:** run the metrics, tick the stage's done-when, and push the branch (a backup; nothing
   merges yet).
4. **Merging:** once, at the end, as a fast-forward of `phase-1`. No feature work lands on `phase-1` meanwhile, so the
   merge can't conflict, and `phase-1` never holds a half-refactored tree. If we pause midway, the branch is
   usable as it stands: every commit is green and golden.
5. **Behaviour changes are not refactoring.** A bug found on the way is written under §7 (found along the way) and
   fixed after the merge, with your approval and a deliberate golden update.
6. **TDD for new domain types** (R4, R5): tests first (red), implementation (green), then move the world onto them
   with the golden master watching.
7. **Performance budget:** scripted runs stay within 25% of today's (200 cycles in about 0.7 s of simulation).

---

## 3. Stages

Sizes are relative (S, M, L, XL). Tick each item when it's committed.

### R0. Safety net (S)
- [x] R0.1 Golden-master harness and fixtures in `tests/golden/` (§2), run alone with `pytest -m golden`
- [x] R0.2 Recording wrapper that captures what each co-op is told (tests only)
- [x] R0.3 Mutation check: changing one posting fails the golden master (proved, then reverted). 1 Oct: the earner's
      share minus 1 µcr failed `postings`; one changed word in a message to a co-op failed `told`.
      Lesson: after reverting a mutation, delete `__pycache__`: a revert in the same second with the same file size
      leaves stale bytecode that Python still trusts
- [x] R0.4 `tests/test_layers.py`: the dependency rule from the AST, with today's violations as named exceptions
      (13 outward imports, 9 imports inside functions; both lists may only shrink)
- [x] R0.5 `tools/arch_metrics.py`: the audit's measurements, with a baseline recorded here. Baseline (1 Oct):
      8,522 lines; package cycles console↔sim, runtime↔sim, sim↔society; largest class `World` 1,009 lines; 2 classes
      over 300 lines; functions over 70/40/30 lines: 6/13/22 (longest `create_app`, 155); 11 imports inside
      functions; 63 status-string comparisons; 7 economy-flag checks; about 17 cross-object private accesses
- [x] **Done when:** the golden master passes twice on an untouched tree and catches a one-character change

### R1. Quick wins, in place (M) — D1 to D6, C3 (part), A6
- [x] R1.1 `JsonlLog` (append, incremental read, read all), used by ratings and the gate (D1, D6)
- [x] R1.2 One backend factory with the spend check, used by every command (D2, S5)
- [x] R1.3 Live economy defaults in the kernel; packs override only what differs (D3)
- [x] R1.4 `LLMGrader` adds the answer format itself; packs drop their copies (D4)
- [x] R1.5 One `society_folder(name)` helper (D5)
- [x] R1.6 StrEnums for job, contract, venture and request statuses (plus proposals, goals and ideas) in
      `sim/status.py` (C3). Status-string comparisons 63 → 3; the last 3 are in the scripted strategies, which can't
      import `sim` yet: they convert in R3. Event-kind constants are dropped from this item: R7's typed events replace
      the kinds, so constants now would be thrown away
- [x] R1.7 Delete `protocol.gate` and `protocol.governance` and any other unused code (A6). Also deleted:
      `contract.settle` and `knowledge.royalty` messages, the meter's per-task budgets (the operator's per-turn
      thinking budget replaced them), `Meter.can_afford`, `Hub.kinds`, `MemoryBus.headroom`, unused imports and
      variables (pyflakes is clean). Kept, though unused today, because the roadmap needs them: the workspace sandbox
      (Phase 2's product files), `RedisBus` (several processes), `Ledger.add_capital` (real money in)
- [x] **Done when:** these duplicates are gone; golden identical

### R2. Break the cycles, in place (M) — A1, A2, S8
- [x] R2.1 Grading types (`Grade`, `Grader`, `StubGrader`, quality tags) in a module that imports nothing of `sim`
      (`society/grading.py` for now; R3 moves it to `domain/market/grading.py`). The sim↔society cycle is gone
- [x] R2.2 The model port (`ModelBackend`, `Completion`, `Turn`, `ToolCall`, `ToolResult`, `Usage`) in a neutral module
      (`sim/ports.py`; `Usage` stays in `substrate/meter.py`, below both). `sim` no longer imports the runtime's backends
- [x] R2.3 The world receives its ledger, bus, hub, activity log and web; a factory builds the defaults
      (`_default_ledger`, `_default_bus`, `_default_activity`). The web is a port (`sim.ports.WebPort`, with `Page`,
      `SearchResult`, `WebError`, `host_of`); `runtime.web.WebAccess` implements it
- [x] R2.4 No function-level imports of our own modules (11 → 0)
- [x] **Done when:** no import cycles; the layer test's exceptions shrink; golden identical. 1 Oct: the cycles left
      (console↔sim, runtime↔sim) come only from the command-line scripts that still live in `sim/` (`live`, `found`,
      `calibrate`); they are 7 of the layer test's exceptions (13 → 7) and go when R3 moves the scripts to `interfaces`

### R3. The new layout (L, mechanical) — A3
- [x] R3.1 Create `commons/` with `domain`, `substrate`, `application`, `agents`, `adapters`, `interfaces`, `protocol`
- [x] R3.2 Move modules (`git mv`, so history follows), splitting the pure halves into `domain`: `gate`, `ventures`,
      `archive`, `founding`, `operator`, `ratings`, and compute prices out of the meter. `population` had no pure half
      worth splitting (R6 revisits it)
- [x] R3.3 Rewrite imports by script (symbol by symbol, so model-port types resolve to `application.ports`);
      `pyproject.toml` packages; a `commons` console script with subcommands (run, sim, found, approve, rate, calibrate)
- [x] R3.4 Old entry points (`python -m sim`, `sim.live`, `sim.found`, `sim.rate`, `sim.approve`, `sim.calibrate`) as shims
      that print the new command and run it
- [x] R3.5 Tests updated to the new imports, unchanged in logic (regrouping them by layer is R12.1). The layer test
      is rewritten for the new layers and passes with no exceptions; the last 3 status strings converted
- [x] R3.6 Docs: every path in `COMMONS.md`, `CHECKLIST.md`, `FRAMEWORK.md`, READMEs and examples updated; code
      docstrings and messages too. `COMMONS.md`'s layers and module map rewritten for the new layout; the README
      rewritten; `docs/COMMANDS.md` written now (every command, every option), so the shims have somewhere to point
- [x] **Done when:** golden identical; every documented command works; layer exceptions are only those R4 to R10 remove
      (there are none: the layer test passes with an empty exception list)

### R4. Aggregates, test-first (L) — C2, C3, C4 (part)
- [x] R4.1 `Contract` aggregate: transition table, a method per move, `DomainError` on illegal moves (tests first:
      `tests/domain/test_contract.py`, 21 tests, written red then made green)
- [x] R4.2 Contract code in the world and executor uses the aggregate: every contract state change is a method of
      `Contract` (no assignments to its status, winner, price, deadline or flags outside it)
- [x] R4.3 `Job` aggregate: lifecycle, value with quality pay, bond, completeness, deferral (tests first:
      `tests/domain/test_job.py`, 9 tests). The class keeps the name `MarketJob`
- [x] R4.4 Job code in the world and executor uses the aggregate. Two detours went with it: passed jobs used to be set
      back to `claimed` before paying (after a deferred outcome, and when grants were shared) only so the old code path
      would accept them; the aggregate pays from `graded` directly. Golden identical
- [x] R4.5 `Micros` (`domain/money.py`) and id NewTypes (`domain/ids.py`) on money and id parameters across domain,
      substrate, application and agents (the wire messages in `protocol` keep plain types)
- [x] **Done when:** no status comparisons outside the aggregates; golden identical. Amended 1 Oct: no status *changes*
      outside the aggregates (none remain). Reading a status to select ("the open contracts") stays where the query is,
      through the enums; moving every query into the aggregates would add methods without adding safety

### R5. The economy as a policy, test-first (M) — S4
- [x] R5.1 `PaymentPolicy` with `MarketPayment` and `GrantPayment` (tests first: `tests/domain/test_economy.py`);
      `policy_for` is the one place the economy setting is read
- [x] R5.2 `Treasury` rules: floor, upkeep, revenue split, bonds (tests first: `tests/domain/test_treasury.py`), as pure
      functions in `domain/treasury.py`; the ledger, the world and the executor apply them (the bond was computed twice,
      the earner's share recomputed after the split)
- [x] R5.3 The world uses the policy; `economy ==` checks removed everywhere, dashboard included (the only ones left
      are in `policy_for`, which reads the setting once). The world also accepts a policy directly
- [x] **Done when:** adding an economy means adding one class; golden identical. Proved by a test: a toy "patron"
      economy, one class, runs a society with no other change

### R6. Split the world (XL) — S1, C1, C4, C8
- [x] R6.1 `cycle.py`: the phases in order, each marked inside or outside the lock; a test holds the order to the
      module's own documentation
- [x] R6.2 Services: contract-net (`ContractNet`), the job board with claims (`JobBoard`), grading with deferred
      settlement and audits (`Grading`), in `application/services/`. Moved verbatim by a tool that rewrites references
- [x] R6.3 Services: ventures (`VentureDesk`), payments with the economy's pool and queue (`Payments`), ratings
      (`RatingDesk`). The scorecard is evaluated by the recorder, so it moves with it in R6.5
- [x] R6.4 Services: web and gate (`WebDesk`), upkeep (`Upkeep`: floor and waking). Population no longer touches the
      world's privates: one sequencer (`world.ids`) numbers jobs, ventures, ideas and goals, and proposals, and the
      world's shared helpers are public (`tell`, `send`, `stat`, `standing`, `add_community`, `turn`). Knowledge and the
      archive stay as world state (`library`, `archive`) with `add_playbook`: three lines don't need a service
- [x] R6.5 Services: gossip (`GossipService`) and the recorder (`Recorder`: tallies, snapshots, the scorecard, the
      `world.cycle` telemetry, `summary`)
- [x] R6.6 `ObservationBuilder` (`application/observe.py`) replaces `World.observe`, built in five sections (the co-op,
      its work, its neighbours, its plans, its surroundings); `world.observe(c)` stays as a one-line facade
- [x] R6.7 `Society` facade (`application/society.py`) with today's `World` API (`World` kept as an alias). Its
      constructor is four named steps (connect, open records, start services, genesis); `VentureDesk.appraise` split
      in three; the dashboard reads the meter through a public property
- [x] **Done when:** `Society` under 250 lines; no class over 300 or function over 40 lines (tables excepted); no
      cross-module private access; golden identical. 1 Oct: `Society` under 250 lines; in the application layer no function
      is over 40 lines and no class over 300 except `Actions` (410, R8's job); no cross-module private access. Long
      functions left elsewhere belong to R10 (the LLM agent), R11 (the dashboard) and, added here, two model-backend
      `chat` methods (46 and 43 lines) for R12

### R7. Domain events (M) — D7
- [x] R7.1 Typed events (`domain/events.py`) and a dispatcher (`application/events.py`); subscribers for what co-ops
      are told (`notices`) and telemetry (`telemetry`), one function per event type. The activity log already derives its
      change entries from telemetry, so it needs no subscriber of its own
- [x] R7.2 Contract and job events moved onto it (one family per commit): 14 contract events, 11 job events, and
      the grading pair (`ModelCalled`, `PartGraded`), published exactly where the telemetry used to be emitted
- [ ] R7.3 Venture, population, grant, rating and gate events moved onto it
- [ ] **Done when:** no direct `_tell`, `hub.emit` or `activity.add` in services; golden identical

### R8. Commands (M) — C6, S2, S7 (part)
- [ ] R8.1 Middleware chain (operator limits, lock, activity log) declared per command; no `setattr` at import
- [ ] R8.2 The executor split by area behind one facade with today's method names
- [ ] R8.3 Role interfaces for agents; `ActionsAPI` is their union
- [ ] **Done when:** any command's call path is readable from its definition; golden identical

### R9. Configuration (S) — S7, D3
- [ ] R9.1 Grouped, typed configs (economy, contracts, population, knowledge, runtime, storage)
- [ ] R9.2 Compatibility constructor for today's flat names; packs override by group
- [ ] **Done when:** no service reads a group it doesn't own; golden identical

### R10. Agents (M) — S3, S6
- [ ] R10.1 `Agent` protocol; the LLM agent no longer inherits the scripted strategy
- [ ] R10.2 `StewardLoop`, `MemberWorker`, `prompts.py` split out of `LLMStrategy`
- [ ] **Done when:** no function over 40 lines in `agents/`; golden identical

### R11. Interfaces and commands (M) — A5, S3, C1
- [ ] R11.1 One `commons` CLI with subcommands and a testable `main(argv)`; nothing runs at import
- [ ] R11.2 Scripts grouped: run, sim, found, approve, rate, calibrate, plus `metrics` and `golden` (the update
      command, guarded); shims for the old paths print the new command
- [ ] R11.3 `docs/COMMANDS.md`: every command and script, with its purpose, every option, examples, what it reads
      and writes, what it costs, and its safety limits
- [ ] R11.4 Dashboard: queries in `application/queries.py`, panel builders, thin routes; JSON identical by test
- [ ] **Done when:** `create_app` under 60 lines; every command documented and tested through `main(argv)`

### R12. Tests and docs (M) — C5, C7
- [ ] R12.1 Tests regrouped by layer and context; acceptance tests in `tests/acceptance/`
- [ ] R12.2 No test touches a private member
- [ ] R12.3 `docs/ARCHITECTURE.md`: layers, the dependency rule, patterns, and how to add a pack, economy, tool,
      backend or metric
- [ ] R12.4 `COMMONS.md`, `CHECKLIST.md`, `FRAMEWORK.md`, the review doc and memory updated
- [ ] R12.5 Fast-forward `phase-1`, push
- [ ] **Done when:** the layer test has no exceptions; every audit finding is closed or explicitly deferred

---

### Proposed: R13. Type checking (needs your decision)
- With named types in place, a type checker can hold them. `pyright` (basic mode) reports 247 errors today, mostly
  `None` handling and loosely typed dicts. Proposed: make it clean, then run it in the test suite so it stays clean.
  Not started: it wasn't in the approved scope.

## 4. Risks and how they're handled

| Risk | Handling |
|---|---|
| The golden master is too brittle (dict order, float formatting) | Normalise before comparing: sorted keys, fixed float rendering; R0 proves it catches real changes |
| Thread timing changes results | The golden runs are sequential (`parallel_turns` off), as scripted runs are today; parallel behaviour is covered by existing tests |
| Event order shifts in R7 | One event family per commit, golden after each |
| The big move (R3) breaks docs and muscle memory | Shims for old commands; docs updated in the same stage; `docs/COMMANDS.md` in R11 |
| Scope creep ("while we're here…") | Behaviour changes are written under §7 and done after the merge |
| Performance (events, indirection) | Measured at every stage against the 25% budget |

## 5. Decisions (1 Oct)

1. **Scope:** the full route, R0 to R12.
2. **Layout:** move to `commons/{domain,application,adapters,agents,interfaces}`. The work so far is treated as the
   proof of concept; this puts the proper architecture under it.
3. **Commands:** the old `python -m sim.*` paths stay as shims that print the new command. Every command and script
   is documented in full (`docs/COMMANDS.md`), and grouped into one `commons` CLI.
4. **Unused code:** deleted when nothing needs it going forward.
5. **Merging:** commit and full test after every item; push after every stage; one fast-forward merge at the end.

## 6. Done when (the whole refactor)

- The layer test passes with no exceptions; no import cycles; no function-level imports of our own modules.
- No class over 300 lines, no function over 40 (declared tables excepted); `Society` under 250 lines.
- No cross-module private access, in code or tests.
- A new economy, model backend, tool, metric or pack is added by writing one class or module, without editing
  conditionals elsewhere.
- The golden master is unchanged from R0; all of today's tests pass, regrouped; tests for the new domain types were
  written first.
- `docs/ARCHITECTURE.md` explains the result.

## 7. Found along the way

Behaviour issues noticed during the refactor, to fix after the merge. Each is kept exactly as it was until then.

1. **Withdrawn contracts are sometimes never closed** (R4.2). When a prime does a part itself, the executor withdraws
   that part's open contracts without setting `closed` or emitting the `contract.stage` event, so they are never
   pruned and the dashboard never sees the withdrawal. When a job fails, its open contracts are withdrawn properly.
   Fix: `withdraw(at=self.w.cycle)` plus the stage event in `do_part`.
