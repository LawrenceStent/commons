# Architecture audit (1 Oct 2026)

An assessment of the codebase at `85160fc` (end of K5), against Clean Code and Clean Architecture, DRY and SOLID,
and whether it follows a settled design pattern. The refactor this leads to is in `docs/REFACTOR-PLAN.md`.

Scope: about 8,500 lines of Python in 7 packages (`substrate`, `protocol`, `society`, `sim`, `runtime`, `console`,
`packs`), plus 2,900 lines of tests (228 tests, all passing). Every number below was measured on that commit.

---

## 1. Verdict

**The behaviour is sound; the structure has outgrown its shape.** The system's rules are well thought out and
well tested: money is conserved and checked, critical decisions are deterministic world rules, runs are
reproducible by seed, and packs plug in without touching the kernel. What has not kept up is the code's
organisation. Five phases and five framework steps were each added to the same few places, so:

- one class, `World`, does almost everything (about 1,000 lines, 64 methods, 15 or so responsibilities)
- the packages depend on each other in cycles, held together by imports inside functions
- the design pattern is implicit and mixed: a transaction script in `World`, plain data classes for the domain,
  Protocol-typed ports in some places and concrete classes in others

**It does not follow a settled pattern today.** Parts of Ports and Adapters are already there (`Grader`, `Appraiser`,
`WorkSource`, `ModelBackend`, the web `Transport`, packs as plugins). The refactor should finish that job rather
than invent a new one.

**Recommendation: refactor, in stages, towards Ports and Adapters (hexagonal architecture), with Domain-Driven
Design's tactical patterns where they pay** (aggregates for jobs and contracts, value objects for money and
identifiers, domain events, policies), **and test-driven development from here on.** A golden-master test guards
behaviour throughout: every stage must leave scripted runs byte-identical.

---

## 2. What is good (keep it)

| Strength | Where |
|---|---|
| Rules over judgement: critical checks are deterministic functions, not prompts | `World.eligible`, `ventures.check`, the gate, the citation rule |
| Money is double-entry, integer, per currency, and checked (`ledger.check()`, total is zero) | `substrate/ledger.py` |
| Reproducible: seeded RNGs per co-op, fixed verdict order after parallel grading | `World.__init__`, `settle_grading` |
| Packs as plugins: a second society arrived without kernel changes specific to it, and a test keeps domain words out of the kernel | `sim/pack.py`, `tests/test_kernel.py` |
| Ports already typed as Protocols in places | `Grader`, `Appraiser`, `WorkSource`, `ModelBackend`, `Transport` |
| Untrusted text is fenced everywhere it reaches a model | grader, appraiser, render, members |
| Behaviour-level tests, including acceptance tests that prove mechanisms (control runs) | `tests/test_phase0_acceptance.py`, `test_k2.py` |
| Docstrings explain why, not what | throughout |

---

## 3. Findings

Severity: **H** high (shapes everything else, or a real risk), **M** medium, **L** low.

### 3.1 Architecture and dependencies

| # | Finding | Evidence | Sev |
|---|---|---|---|
| A1 | **Package cycles.** `sim` ↔ `runtime` (`sim/grader.py`, `sim/ventures.py` and `sim/founding.py` import `runtime.backends`; `runtime/steward.py` imports `sim.market`). `society` ↔ `sim` (`society/strategies/*` import `sim.market`; `sim` imports `society`). | import graph | H |
| A2 | **Imports inside functions to dodge those cycles**: 11 of them. | e.g. `sim/engine.py:787` `runtime.web`, `sim/founding.py:229` `society.community` | M |
| A3 | **No layer boundaries.** The domain (jobs, contracts, money rules), application flow (the cycle), infrastructure (SQLite ledger, files, HTTP) and interfaces (CLIs, FastAPI) are mixed. `sim/` alone holds all four. | `sim/` contents | H |
| A4 | **The world builds its own infrastructure**: `Ledger(SQLite)`, `MemoryBus`, `Hub`, `ActivityLog` (file) are constructed inside `World.__init__`. Nothing can be substituted except through `Params` strings. | `sim/engine.py:213` | M |
| A5 | **Composition roots are scripts that run at import** (`sim/live.py`, `found.py`, `rate.py`, `approve.py`, `calibrate.py`): argparse at module level, so they can't be imported or tested. | each CLI | M |
| A6 | **Dead protocol code**: `protocol.gate` and `protocol.governance` messages are used by nothing (the gate went in-process in K5). | grep | L |

### 3.2 SOLID

| # | Principle | Finding | Evidence | Sev |
|---|---|---|---|---|
| S1 | **Single responsibility** | `World` is a God object: the cycle, upkeep and floor, job posting, claim allocation, the contract-net, deadlines, grading and deferred settlement, audits, ventures, grants, ratings, the web and gate, playbooks, observation building, gossip, recording and the scorecard. | 1,009 lines, 64 methods | H |
| S2 | Single responsibility | `Actions` (41 methods) is every command any agent can issue, plus billing, transcripts and operator plumbing. | `sim/actions.py` | M |
| S3 | Single responsibility | `LLMStrategy.commission` (86 lines) builds prompts, runs a tool loop, bills, stores drafts. `create_app` is 155 lines and `snapshot` 122. | `runtime/steward.py:209`, `console/app.py` | M |
| S4 | **Open/closed** | The economy is a flag checked in 7 places (`economy == "grant"`) rather than a policy object. Adding a third economy (trading's capital economy, K6) means editing every one. | `sim/engine.py` (6), `console/app.py` (1) | H |
| S5 | Open/closed | Backend selection is an if/elif chain copied into 3 CLIs; adding a backend edits all three. | `live.py`, `found.py`, `calibrate.py` | M |
| S6 | **Liskov** | `LLMStrategy` inherits `Strategy` but replaces `turn` wholesale, inheriting about 20 scripted hooks it never uses. Code that relies on the hooks would break for it. | `runtime/steward.py:48` | M |
| S7 | **Interface segregation** | `Params` is one bag of 62 fields (economy, contract-net, population, concurrency, persistence, logging). Every module depends on all of it. `Observation` has 38 fields; `ActionsAPI` is every command at once. | `sim/engine.py:71`, `society/observation.py` | M |
| S8 | **Dependency inversion** | The domain depends on concretions: `sim.grader` on `runtime.backends`, `society.strategies` on `sim.market.StubGrader`, `World` on `runtime.web`. | A1 | H |

### 3.3 DRY

| # | Duplication | Where | Sev |
|---|---|---|---|
| D1 | Append-only JSONL with an incremental read offset, written twice; plus two "read all lines" helpers | `sim/ratings.py`, `sim/gate.py` | M |
| D2 | Backend construction and the spend check, three times | `sim/live.py`, `sim/found.py`, `sim/calibrate.py` | M |
| D3 | The live economy (19 parameters) copied between packs | `packs/*/__init__.py` `LIVE_PARAMS` | M |
| D4 | The grader's answer format restated in each pack's prompt, although the code that parses it never changes | `sim/grader.py`, both packs | L |
| D5 | "Find a society folder and check it exists", three times | `sim/rate.py`, `sim/approve.py`, `sim/founding.py` | L |
| D6 | Run-prefixed ids for files shared across runs, implemented twice | `ratings.py`, `gate.py` | L |
| D7 | Every change is reported up to three times by hand: `_tell` (37 calls), `hub.emit` (23) and `activity.add` | `sim/engine.py` | M |

### 3.4 Clean Code

| # | Finding | Evidence | Sev |
|---|---|---|---|
| C1 | **Long functions**: 6 over 70 lines, 13 over 40, 22 over 30. | `create_app` 155, `snapshot` 122, `commission` 86, `render` 83, `turn` 78, `observe` 74; then `World.__init__` 67 | M |
| C2 | **Anaemic domain model**: `MarketJob` and `Contract` are data bags; their lifecycles (open, claimed, graded, paid, failed; open, awarded, delivered, accepted…) are enforced by scattered `if status == "..."` checks. | 60 status-string comparisons | H |
| C3 | **Primitive obsession**: money is a bare `int` of µcr everywhere; ids, statuses and event kinds are bare strings. | throughout | M |
| C4 | **Encapsulation breaches**: other modules use `World` privates (`_tell`, `_send`, `_standing`, `_add_community`, `_plan_seq`, `_venture_seq`, `_proposal_seq`). | `sim/population.py`, `sim/actions.py`, `sim/ventures.py` | M |
| C5 | **Tests reach into privates** (`w._allocate_claims`, `_try_grade`, `_fund_grants`, `_award_grants`, `_add_community`; 19 calls), a sign the seams are missing. | `tests/` | M |
| C6 | **Metaprogramming at import**: `Actions` methods are replaced in loops with `setattr` (logging, operator limits, locking, plus an `UNLOCKED` exception set). Correct, but the call path is invisible from the method. | `sim/actions.py:452-485` | M |
| C7 | **Tests are organised by delivery phase** (`test_k2`, `test_k4`, `test_k5`), not by behaviour or context, so finding the tests for contracts or money means knowing the project's history. | `tests/` | L |
| C8 | **Concurrency is ad hoc**: one global `RLock`, with web calls deliberately outside it and an activity-log lock added later. Correct today; easy to break. | `World.lock`, `Actions`, `ActivityLog` | M |

---

## 4. Which pattern, and why

| Option | Fit |
|---|---|
| **Ports and Adapters (hexagonal), with DDD tactical patterns** | **Recommended.** Half of it is already there (Protocol ports, packs as plugins). It gives a rule anyone can check: the domain imports nothing but itself; adapters import inward. Aggregates fix C2. Policies fix S4. Domain events fix D7. |
| Full DDD (bounded contexts as separate packages with repositories, an anti-corruption layer per context) | Too much ceremony for a single-process simulation whose state lives in memory. Borrow its tactical patterns, not its strategic machinery. |
| Clean Architecture (entities, use cases, interface adapters, frameworks) | The same dependency rule as hexagonal, with more layers. Hexagonal is the lighter way to the same place. |
| Keep the current shape and fix hotspots | Cheapest now, but K6 (a capital economy, deterministic evaluator) and Phase 2 (real money, publishing) would land in the same God object. |

**Test approach:** TDD for everything new, starting with the aggregates. For the refactor itself, a **golden master**
(characterisation tests) pins today's behaviour: scripted runs on seeds 0, 3 and 7 for both packs, plus a fake-model
live run, must produce byte-identical ledgers, activity logs and summaries after every stage.
