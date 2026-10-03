# Architecture

How Commons is built, and how to extend it. For what it is and why, see `COMMONS.md`; for every command, `COMMANDS.md`;
for how we got here, `ARCHITECTURE-AUDIT.md` and `REFACTOR-PLAN.md`.

## 1. Layers

Ports and adapters (hexagonal), with domain-driven design inside. Each layer imports only the layers inside it:

    protocol < domain < substrate < application < agents < adapters < interfaces < packs

| Layer | Folder | What lives there | Knows about |
|---|---|---|---|
| protocol | `commons/protocol/` | Signed messages between co-ops (envelope, contract, knowledge, population, reputation verbs) | nothing |
| domain | `commons/domain/` | The rules: aggregates (Contract, MarketJob), value objects, statuses, money (`Micros`), economies, packs, scorecards, reputation, the gate's policy, domain events | protocol |
| substrate | `commons/substrate/` | Infrastructure every society runs on: ledger, bus, meter, registry, telemetry hub, activity log, JSONL files | protocol, domain |
| application | `commons/application/` | The society and its use cases: the `Society` facade, services, the cycle, commands, observations, events dispatch, read models, params, ports | everything inside it |
| agents | `commons/agents/` | Who decides: scripted strategies, the LLM steward and its members, who to wake | everything inside it |
| adapters | `commons/adapters/` | The outside world behind ports: model backends (Anthropic, LM Studio, fake), the web, Redis | everything inside it |
| interfaces | `commons/interfaces/` | How you drive it: the `commons` command (`cli/`) and the dashboard (`console/`) | everything inside it |
| packs | `packs/` | What one society is *for*: work, capabilities, prompts, calibration cases, scorecard | everything |

**The dependency rule is a test, not a convention.** `tests/architecture/test_layers.py` parses every import (type-only
imports included) and fails on any that points outward, on any import of our own code hidden inside a function, and on
any domain import of something other than the protocol and the domain. It has no exceptions list in use; keep it that
way.

The application talks to the outside through **ports** (`commons/application/ports.py`): `ModelBackend` and `WebPort`.
Adapters implement them. Tests use the fakes.

## 2. Patterns

| Pattern | Where | Rule |
|---|---|---|
| Aggregates with transition tables | `domain/contract.py`, `domain/market.py` | State changes only through methods; an illegal move raises `DomainError`. Never assign `.status` from outside. |
| Statuses as `StrEnum` | `domain/status.py` | No status strings anywhere else. |
| Money as `Micros` (int), ids as `NewType` | `domain/money.py`, `domain/ids.py` | One µcr is 10⁻⁶ credit. Ids come from `Sequences` (`domain/ids.py`), never from counters in services. |
| Domain events | `domain/events.py` (≈50 dataclasses) | Services publish events; they don't format messages or emit telemetry themselves. |
| Event subscribers by type | `application/events.py` | `notices`, `activity` and `telemetry` are `functools.singledispatch` functions. `notices` and `telemetry` must be defined for every event (a missing one raises). |
| Facade + services | `application/society.py`, `application/services/` | `Society` (alias `World`) holds state; each service has one responsibility (board, contract net, grading, payments, ventures, web, upkeep, ratings, gossip, recorder). |
| Fixed cycle | `application/cycle.py` | `PHASES`: an ordered list, each phase marked locked or unlocked. Model and web calls happen outside the lock. |
| Command pipeline | `application/commands/pipeline.py` | Every command is declared with `@command(log=…, lock=…)`: lock, activity log and operator limits wrap it. Commands return `Outcome`s, never raise at agents. |
| Strategy (economies) | `domain/economy.py` | A `PaymentPolicy` chosen once by `policy_for`; nothing else asks which economy it is. |
| Strategy (agents) | `domain/community.py` (`Agent` protocol) | Scripted and LLM strategies are interchangeable; they act only through `Actions`. |
| Read models | `application/queries.py` | The dashboard reads; reading changes nothing. Bounded by the telemetry rings, not by run length. |
| Settings as frozen groups | `application/params.py` | `params.<group>.<field>` (run, money, market, contracts, ventures, population, knowledge, trust, runtime, storage). |
| Rules over judgement | the gate, operator limits, citation rule, part formats | Anything critical is a world function the agent can't talk its way past, not a prompt. |

## 3. Testing

Test first. Tests are grouped by layer (`tests/<layer>/`) with whole-society behaviour in `tests/acceptance/`.

- **No test touches a private member.** If a test needs a seam, add a public one (e.g. `LMStudioBackend(post=…)`,
  `MemoryBus.backlog()`, `Hub.kept()`).
- **Golden master** (`tests/golden/`): 8 seeded runs × 5 streams, and the dashboard JSON for both packs. A refactor
  must leave it unchanged. Regenerate only for an intended change: `uv run commons golden --update --approved "why"`.
- **Commit gate:** `uv run pytest -q > runs/pytest.log 2>&1; rc=$?` and commit only on `rc == 0`. Never pipe pytest.
  After a mutation test, delete `__pycache__` (a stale `.pyc` of the same size and second survives).

## 4. How to add…

### A pack (a new kind of society)
1. Make `packs/<name>/__init__.py` exporting `PACK = Pack(...)` (`domain/pack.py` lists every field).
2. Give it a `work_source`: a `TemplateWorkSource(subjects, templates)` is enough when work is "do these parts for X";
   otherwise write a class with `new_job(rng, job_id, cycle, reward, board_ttl, parts)`.
3. `population` (scripted co-ops, for tests and golden) and `live_population` (LLM co-ops).
4. Formats, if a capability's text has countable rules (a word range, required sections): `formats=` on the
   `TemplateWorkSource`, as `Format`s (`domain/format.py`). They are checked at hand-in, before any grader; members are
   told them and revise once if they miss.
5. Prompts (`grader_system`, `appraiser_system`, `member_system`) and calibration cases in `packs/<name>/calibration.py`;
   check them with `uv run commons calibrate --pack <name>`.
6. A `scorecard` of `Metric`s if success isn't money.
7. Add an acceptance test in `tests/acceptance/test_packs_on_the_kernel.py` and golden runs for it.

The kernel must not mention the pack by name; packs import the kernel, never the other way.

### An economy (how passing work is paid)
1. Add a frozen dataclass implementing `PaymentPolicy` in `domain/economy.py` (`funding`, `shares`, `view`, and the
   ledger account names it uses).
2. Add its name to `policy_for`.
3. Test its `shares` and `funding` in the domain, then a society test that runs with `economy="<name>"`.

### A tool (something a co-op can do)
1. A command method on the right mixin in `application/commands/<area>.py`, decorated `@command()`. Validate, use
   capacity if it's work, move money only through the ledger, publish a domain event, return an `Outcome`.
2. The event in `domain/events.py`, with its `notices` and `telemetry` in `application/events.py`.
3. The tool's schema in `agents/llm/tools.py` (the description is the model's only instruction: what it does, what it
   costs, when it's refused). Add a `CALLS` entry in `agents/llm/steward.py` if its arguments need converting.
4. Tests in `tests/application/` for the command and `tests/agents/` for the tool call. Golden must not move unless
   scripted strategies use it.

### A model backend
1. A class in `adapters/models.py` implementing `ModelBackend` (`structured` and `chat`, `name`, `real`). Translate
   messages in module functions, not in `chat`. Take the transport as a constructor argument so tests can fake it.
2. Add it to `BACKENDS` and `choose_backend`. A backend that costs real money must require `--yes-spend`.
3. If it costs real money, add its list prices to `PRICES` in `domain/compute.py`; the meter (`substrate/meter.py`)
   debits every call at those prices.

### A metric
1. A function `World -> float | None` (None: no data yet) in `domain/scorecard.py`, reading the society's public
   records only.
2. Wrap it in a `Metric(key, title, measure, by=…, target=…, floor=…)` and add it to a pack's `scorecard`, or to
   `GENERAL` if every society should have it.
3. A unit test with a hand-built society, and check the dashboard's scorecard panel.

### A web capability
Behind `WebPort` (`application/ports.py`), implemented in `adapters/web.py`, requested through the gate
(`application/gate.py`, policy in `domain/gate.py`) and run by `services/web.py` outside the lock. Nothing reaches the
network without the gate's approval.

## 5. Money

SIM credits exist only in simulations, and a live society is real USD end to end. The ledger keeps them apart and
never adds one currency to the other (`substrate/ledger.py`).
