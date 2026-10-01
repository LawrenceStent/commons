# Refactor plan: towards Ports and Adapters, with DDD tactics and TDD

Follows from `docs/ARCHITECTURE-AUDIT.md` (finding ids such as S1 or D3 refer to it). Branch:
`refactor/architecture`, cut from `phase-1` at `85160fc`. No feature work on `phase-1` until this merges back.

**The rule of this refactor: behaviour does not change.** Every commit passes the full test suite and a golden-master
test that pins today's runs byte for byte. Anything that would change behaviour is out of scope, or goes to you as
a separate, labelled decision.

---

## 1. Target architecture

### 1.1 The dependency rule

```
                 interfaces  (CLI, dashboard)            ─┐
                 agents      (LLM steward and members,     │  outer: may import anything inward
                              scripted strategies)         │
                 adapters    (SQLite ledger, bus, files,   │
                              HTTP, model backends)       ─┘
                 application (the society, the cycle,     ─┐
                              services, commands, ports)   │  inner: imports only domain
                 domain      (pure rules and models)      ─┘  innermost: imports nothing of ours

  packs/  plug-ins: import domain and application only
  protocol/  signed messages: imported by domain and adapters; imports nothing of ours
```

- **domain**: no I/O, no threads, no clock, no models, no randomness except an RNG passed in. Testable in microseconds.
- **application**: orchestrates the domain through **ports** (Protocols it owns: `ModelBackend`, `Grader`,
  `Appraiser`, `Ledger`, `WebAccess`, `Store`, `Clock`). Holds the world's lock and the cycle.
- **adapters**: implement the ports (SQLite, Redis, JSONL files, urllib, Anthropic, LM Studio, fakes).
- **agents**: what plays a co-op, through the observation and command APIs only.
- **interfaces**: composition roots. They build adapters, wire them into the application, and expose them.

A test (stage 0) enforces this rule from the AST, listing today's violations as known exceptions that must reach
zero by the end.

### 1.2 Package layout (end state)

```
commons/
  domain/
    money.py          Micros (a NewType over int), Currency, account names, the revenue split
    ids.py            JobId, ContractId, CoopId, RequestId (NewTypes)
    status.py         JobStatus, ContractStatus, VentureStatus, RequestStatus (StrEnum)
    events.py         domain events (JobPaid, ContractAwarded, GateRequested, …)
    market/           job.py (the Job aggregate), grading.py (Grade, quality tags), work.py (WorkSource, TemplateWorkSource)
    contracts/        contract.py (the Contract aggregate and its state machine)
    economy/          payment.py (PaymentPolicy: MarketPayment, GrantPayment), treasury.py (floor, upkeep, bonds)
    reputation.py     (from substrate/reputation.py)
    population.py     proposal rules (from sim/population.py, the rule half)
    ventures.py       rules and value (from sim/ventures.py, the rule half)
    knowledge.py      Playbook, royalties; archive_index.py (BM25 over texts, no files)
    gate.py           GatePolicy, Request, decisions (from sim/gate.py, the rule half)
    scorecard.py      Metric, evaluate, general metrics
    pack.py           Pack (from sim/pack.py)
  application/
    ports.py          every Protocol the application needs
    society.py        Society: the state and the facade (today's World public API, kept)
    cycle.py          the cycle as an ordered list of phases (inside or outside the lock)
    services/         contract_net, claims, grading, ventures, population, grants, ratings, web, knowledge, gossip, recorder
    commands/         the actions executor, split by area, with an explicit middleware chain
    observe.py        ObservationBuilder (the read model a co-op sees)
    queries.py        read models for the dashboard (today's snapshot)
    founding.py       found, approve, load (file access through a port)
  adapters/
    ledger_sqlite.py  meter.py  bus_memory.py  bus_redis.py  telemetry.py  activity_log.py  jsonl.py
    society_folder.py (society.toml, blueprints, questions, operator folder, archive files)
    web_http.py       (from runtime/web.py)
    models/           anthropic.py  lmstudio.py  fake.py
  agents/
    llm/              steward.py (the turn loop)  member.py (the look-up loop and drafts)  render.py  tools.py  prompts.py
    scripted/         base.py  cooperator.py  defector.py  free_rider.py
  interfaces/
    cli.py            one command: commons run | sim | found | approve | rate | calibrate
    console/          app.py (thin routes)  panels.py  dashboard.html
  protocol/           (moved as is)
packs/                (unchanged location)
tests/
  domain/  application/  adapters/  agents/  interfaces/  acceptance/  golden/
```

Old entry points (`python -m sim.live`, `sim.found`, `sim.rate`, `sim.approve`, `sim.calibrate`, `python -m sim`) stay
as thin shims that call the new CLI, until you decide to drop them.

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

1. **Golden master first** (stage 0). It runs scripted societies (seeds 0, 3 and 7, both packs, 200 cycles) and a
   fake-model live society (10 cycles, sequential), and stores, per run:
   - every ledger posting
   - every telemetry event (kind and fields, without wall-clock times)
   - every activity entry (without times)
   - every event each co-op was told (captured by a recording wrapper around each strategy)
   - the summary text

   Each stage must reproduce all of them exactly.
2. **Every commit is green**: `uv run pytest` gated on its exit code (never piped), golden master included.
3. **Behaviour changes are not refactoring.** If a stage finds a bug, it's noted in this file, and the fix goes in
   its own commit, after the refactor, with your approval and a deliberate golden update.
4. **TDD for the new domain types** (stages 4 and 5): write the aggregate's tests first (red), implement (green),
   then move the world onto it (refactor) with the golden master watching.
5. **Small steps**: one move or extraction per commit, with the stage named in the message ("R4: …").
6. **Metrics after each stage** (`tools/arch_metrics.py`): the audit's numbers, so progress is visible.
7. **Performance budget**: scripted runs stay within 25% of today's (200 cycles in about 0.7 s).

---

## 3. Stages

Sizes are relative (S, M, L, XL). The stages are ordered so that each leaves the code better on its own; we can stop
after any of them.

### R0. Safety net (S)
- `tests/golden/`: the harness and fixtures described in §2, plus `pytest -m golden` to run it alone.
- A recording strategy wrapper for told events (only the test uses it).
- `tests/test_layers.py`: the dependency rule from §1.1, checked from the AST, with today's violations listed as known
  exceptions (each with its finding id).
- `tools/arch_metrics.py`: the measurements behind the audit.
- **Done when:** the golden master passes on an untouched tree twice in a row, and fails if one character of a
  posting changes (a deliberate mutation test, then reverted).

### R1. Quick wins, in place (M) — D1 to D6, C3 (part), A6
- `JsonlLog`: append, plus incremental read from an offset, plus read-all. Used by ratings and the gate (D1, D6).
- `backends.from_args(...)`: one place that builds a model backend and enforces the spend flag (D2, S5).
- `LIVE_ECONOMY` defaults in the kernel; packs override only what differs (D3).
- `LLMGrader` appends the answer format itself; pack prompts drop their copies (D4). This changes the prompt text
  sent to models but not any scripted output; it needs a one-line note in the golden fake run if prompts are
  pinned there.
- `society_folder(name)` helper (D5).
- StrEnums for job, contract, venture and request statuses, and constants for event kinds. StrEnum compares equal
  to strings, so this is safe to do one at a time (C3).
- `protocol.gate` and `protocol.governance`: delete, or mark reserved (your decision, §5).
- **Done when:** duplicates gone, golden identical.

### R2. Break the cycles, in place (M) — A1, A2, S8
- Move `Grade`, `Grader`, `StubGrader` and the quality tags out of `sim/market.py` into a grading module that
  `society` and `runtime` can both import without importing `sim`.
- A neutral module for the model port (`ModelBackend`, `Completion`, `Turn`, `ToolCall`, `Usage`). `sim` depends on
  the port; `runtime` implements it.
- The world receives its web, ledger, bus and hub (A4). The defaults are built by a factory, so `World(Params())`
  still works.
- Remove all 11 in-function imports.
- **Done when:** the import graph has no cycles, the layer test's exceptions shrink accordingly, golden identical.

### R3. The new layout (L, mechanical) — A3
- `git mv` into `commons/{domain,application,adapters,agents,interfaces,protocol}` per §1.2, splitting files that
  hold both rules and I/O (`gate`, `ventures`, `population`, `archive`, `founding`) along that line.
- Rewrite imports with a script; update `pyproject.toml` (packages, a `commons` console script); add the old-path shims.
- Move tests into the new tree (no test logic changes).
- **Done when:** golden identical; every documented command still works through the shims; the layer test's
  exceptions are only those R4 to R10 will remove.

### R4. Aggregates, test-first (L) — C2, C3, C4 (part)
- `Contract`: its states and transitions as a table (open → awarded → delivered → accepted | rejected | defaulted;
  open → expired | withdrawn; awarded → failed), methods for each move, illegal moves raise. Unit tests first.
- `Job`: open → claimed → graded → paid | failed; open → expired. Value with quality pay, bond, completeness,
  deferral. Unit tests first.
- The world's contract and job code calls the aggregates; the status checks disappear from services and commands.
- **Done when:** no `status ==` string comparisons outside the aggregates; golden identical.

### R5. The economy as a policy, test-first (M) — S4
- `PaymentPolicy` (fund at cycle start, handle passed work, settle at cycle end, describe for the observation).
  `MarketPayment` pays at once; `GrantPayment` queues and shares the pool.
- `Treasury` rules: floor, upkeep, revenue split, bonds.
- `Params.economy` chooses the policy at construction; no other code checks it.
- **Done when:** zero `economy ==` checks; adding an economy means adding one class; golden identical.

### R6. Split the world (XL) — S1, C1, C4, C8
- One service per responsibility (§1.2 `services/`), each owning its state and exposing a public API. No module
  touches another's privates; the `_seq` counters move into the services that use them.
- `cycle.py`: the phases in order, each declaring whether it runs inside the world's lock (state changes) or
  outside it (model and web calls, results applied under the lock). The order is visible in one place.
- `Society` keeps the `World` public API as a facade (`World` stays as an alias), so the console, packs and tests
  are unchanged.
- `ObservationBuilder` takes over `observe`.
- **Done when:** `Society` under 250 lines; no class over 300 lines, no function over 40 (tables excepted); no
  cross-module private access; golden identical.

### R7. Domain events (M) — D7
- Services emit typed events; three subscribers turn them into what exists today: the co-op's inbox messages,
  telemetry events and activity entries, with the same text, fields and order.
- **Done when:** no direct `_tell`, `hub.emit` or `activity.add` in services; golden identical (this is the stage
  most likely to change event order, so it goes one event family per commit).

### R8. Commands (M) — C6, S2, S7 (part)
- The executor split by area (contracts, knowledge, population, planning, ventures, archive and web, accounting),
  behind one facade with today's method names.
- An explicit middleware chain per command: operator limits, then the lock (web commands declare that they manage it
  themselves), then the activity log. No `setattr` at import.
- Role interfaces for agents (`ContractActions`, `KnowledgeActions`, …); `ActionsAPI` becomes their union.
- **Done when:** the call path of any command is readable from its definition; golden identical.

### R9. Configuration (S) — S7, D3
- `Params` becomes grouped, typed configs (`EconomyConfig`, `ContractConfig`, `PopulationConfig`, `KnowledgeConfig`,
  `RuntimeConfig`, `StorageConfig`), each read only by the services that need it. A compatibility constructor accepts
  today's flat names, so packs and tests keep working.
- **Done when:** no service reads a config group it doesn't own; golden identical.

### R10. Agents (M) — S3, S6
- `Agent` protocol (`turn(obs, act)`); scripted strategies and the LLM agent both implement it, and the LLM agent no
  longer inherits the scripted hooks.
- Split `LLMStrategy`: `StewardLoop` (rounds, nudges, refusal cache, budget), `MemberWorker` (prompt, look-up loop,
  billing, drafts), `prompts.py`.
- **Done when:** no function over 40 lines in `agents/`; golden identical (the fake live run covers this).

### R11. Interfaces (M) — A5, S3, C1
- One CLI, `commons`, with subcommands and a testable `main(argv)`; each subcommand is a composition root. The old
  `python -m` paths become shims.
- Console: dashboard queries move to `application/queries.py`; panel builders replace the 122-line `snapshot`;
  routes become thin. The dashboard's JSON stays identical (a test compares it).
- **Done when:** nothing runs at import; `create_app` under 60 lines; golden identical.

### R12. Tests and docs (M) — C5, C7
- Tests regrouped by layer and context, with phase-acceptance tests kept under `tests/acceptance/`. Tests use public
  APIs only; the five private methods tests use today become public seams or are tested through their services.
- `docs/ARCHITECTURE.md`: the layers, the dependency rule, the patterns, and how to add a pack, an economy, a tool,
  a backend or a metric. `COMMONS.md`'s module map and the checklist updated.
- **Done when:** the layer test has zero exceptions; every audit finding is closed or explicitly deferred.

---

## 4. Risks and how they're handled

| Risk | Handling |
|---|---|
| The golden master is too brittle (dict order, float formatting) | Normalise before comparing: sorted keys, fixed float rendering; R0 proves it catches real changes |
| Thread timing changes results | The golden runs are sequential (`parallel_turns` off), as scripted runs are today; parallel behaviour is covered by existing tests |
| Event order shifts in R7 | One event family per commit, golden after each |
| The big move (R3) breaks docs and muscle memory | Shims for old commands; docs updated in the same stage |
| Scope creep ("while we're here…") | Behaviour changes are written down here and done after the merge |
| Performance (events, indirection) | Measured at every stage against the 25% budget |
| The branch drifts from `phase-1` | No feature work on `phase-1` meanwhile; merge back at the end, or at a stage boundary you choose |

## 5. Decisions for you

1. **The pattern**: Ports and Adapters with DDD tactical patterns, golden-master protection, TDD for new code
   (recommended), or a lighter "fix the hotspots" pass (stages R0, R1, R2, R5 and R6 only).
2. **The layout**: move to `commons/{domain,application,adapters,agents,interfaces}` (recommended: the names say
   what each layer is), or keep today's package names and enforce layers inside them.
3. **Old commands**: keep the `python -m sim.*` shims for a while (recommended), or switch to `commons …` at once.
4. **Unused protocol messages** (`gate`, `governance`): delete (recommended; the bus can grow them back when it
   needs them) or keep as reserved.
5. **Merging**: once at the end (recommended), or after R3 and again at the end.

## 6. Done when (the whole refactor)

- The layer test passes with no exceptions; no import cycles; no function-level imports of our own modules.
- No class over 300 lines, no function over 40 (declared tables excepted); `Society` under 250 lines.
- No cross-module private access, in code or tests.
- A new economy, model backend, tool, metric or pack is added by writing one class or module, without editing
  conditionals elsewhere.
- The golden master is unchanged from R0; all of today's tests pass, regrouped; tests for the new domain types were
  written first.
- `docs/ARCHITECTURE.md` explains the result.
