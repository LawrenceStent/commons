# Commons as a framework: one kernel, many societies

*A plan, written 26 Sep 2026 during Phase 1.5. Nothing here is built yet. It changes the roadmap in
`docs/CHECKLIST.md` (see §11) and extends `docs/COMMONS.md`.*

## Contents

1. [What you asked for](#1-what-you-asked-for)
2. [The idea in one picture](#2-the-idea-in-one-picture)
3. [Kernel vs pack: what stays, what varies](#3-kernel-vs-pack-what-stays-what-varies)
4. [The pack interfaces](#4-the-pack-interfaces)
5. [Passing in context and spawning co-ops](#5-passing-in-context-and-spawning-co-ops)
   - [5b. Measuring success beyond money](#5b-measuring-success-beyond-money)
6. [Principle: effectiveness and efficiency, not speed](#6-principle-effectiveness-and-efficiency-not-speed)
7. [Four societies, sketched](#7-four-societies-sketched)
8. [Running several societies](#8-running-several-societies)
9. [How we get there from today's code](#9-how-we-get-there-from-todays-code)
10. [Pitfalls, and how the plan handles them](#10-pitfalls-and-how-the-plan-handles-them)
11. [Changes to the roadmap](#11-changes-to-the-roadmap)
12. [Decisions for you](#12-decisions-for-you)

---

## 1. What you asked for

1. **Extract the core** so the same machinery can run different kinds of co-operative society, not
   only the one that looks for ways to earn money online.
2. **Spawn societies from context.** Give it a purpose and some material, and it starts a set of
   multi-agent co-ops aimed at that purpose. Examples:
   - trading, where each co-op follows a different strategy
   - tech-for-good initiatives
   - OSINT research
3. **Effectiveness and efficiency, not speed.** The agents are not in a race. What matters is good
   work per unit of thinking.

The good news: most of what exists is already domain-agnostic. The ledger, bus, reputation,
contract-net, population moves, runtime and dashboard don't care what the work *is*. What's
specific to "earn online" is a handful of known places in the code (§3).

---

## 2. The idea in one picture

```
                          ┌──────────────────────────────────────────┐
  you:  brief + context ─►│  FOUNDING   draft co-op blueprints        │─► you approve / edit
        (purpose, docs,   │             (proposed, never imposed)     │
         strategies)      └──────────────────────────────────────────┘
                                             │ genesis
                                             ▼
  ┌──────────────────────────── SOCIETY (one instance) ─────────────────────────────┐
  │                                                                                 │
  │   PACK (what this society is about)            KERNEL (how any society works)   │
  │   ├─ brief: mission, values, limits            ├─ ledger (SIM / USD)            │
  │   ├─ capabilities vocabulary                   ├─ bus + signed protocol         │
  │   ├─ work source: where jobs come from         ├─ reputation, gossip, decay     │
  │   ├─ evaluator: what counts as good work       ├─ contract-net, deadlines       │
  │   ├─ member toolset: what agents can use       ├─ population: spawn/fork/merge  │
  │   ├─ policy: gate rules, forbidden actions     ├─ knowledge: playbooks          │
  │   ├─ economy: funding model, prices            ├─ runtime: stewards, members    │
  │   └─ dashboard: domain KPIs                    └─ meter, kill-switches, console │
  │                                                                                 │
  │   CO-OPS: studio, lab, …   each = charter + doctrine + capabilities + purse     │
  └─────────────────────────────────────────────────────────────────────────────────┘
       own ledger, own bus namespace, own workspaces, own runs/ folder
```

Three words that carry the plan:

- **Kernel**: the mechanism. It is the same for every society. Everything built in Phases 0–1.4 that
  isn't about products and markets.
- **Pack**: a domain. It's a folder that says what a society is *for*: where its work comes from,
  how that work is judged, what tools agents may use, and what they must never do.
- **Society**: one running instance (kernel + pack + a brief + founding co-ops), fully isolated from
  every other society.

A co-op keeps its **charter** (what it's for) and gains a **doctrine** (how it works). For trading,
the doctrine is the strategy you hand it. For OSINT it might be a method or a beat. That is how
"different financial trading strategies per co-op" fits without special code.

---

## 3. Kernel vs pack: what stays, what varies

| Concern | Today (hard-coded for "earn online") | Becomes |
|---|---|---|
| Capabilities | `research, build, design, write` in `sim/market.py` | **Pack**: e.g. trading `research, signal, risk, execution` |
| Where jobs come from | `generate_job` + `PART_TEMPLATES` + `PRODUCTS` | **Pack `WorkSource`** |
| How work is judged | `StubGrader` / `LLMGrader` with market rubrics | **Pack `Evaluator`** (LLM grader, deterministic scorer, human review, or a mix) |
| What value is | Market pays a fixed reward on pass | **Pack**: reward scaled by quality, P&L, impact score, verified findings |
| Who pays for thinking | Purse funded by market revenue | **Pack economy**: market revenue, a grant, or capital allocation |
| Steward's rules of the world | One preamble, partly market-specific | **Kernel preamble** (protocol, money, contracts, reputation) + **pack brief** |
| Tools | 21 kernel tools; members only write text | **Kernel tools** + **pack member tools** (web research, data feeds, paper broker) |
| Safety | Gate schemas only | **Pack policy**: gate rules, forbidden actions, egress allowlist, caps |
| Seed co-ops | `default_population()` | **Blueprints** from founding (§5) |
| Settings | `Params` defaults | **Kernel defaults + pack overrides** |
| Dashboard | Generic panels | Generic panels + **pack KPIs panel** |
| Calibration | `sim/calibration.py` (product-kit cases) | **Pack calibration set** (every evaluator must pass its own) |

Everything else stays in the kernel unchanged: ledger, currencies, bus, signatures, rate limits,
reputation, contract-net and deadlines, spawn/fork/merge/learn, playbooks and royalties, disputes,
the meter and kill-switches, telemetry, the console, the runtime loop, and the scripted characters
(still the regression suite for the kernel).

---

## 4. The pack interfaces

A pack is a folder: `packs/<name>/`, with a declarative `pack.yaml` for everything that is data, and
a small `pack.py` for anything that must be code. The rule: **if it can be data, it is data.**

```
packs/
  earn-online/        pack 0: today's society, moved here with no behaviour change
    pack.yaml
    brief.md          mission, values, limits (cached in the steward's system prompt)
    jobs.yaml         job templates, parts, rubrics
    calibration.yaml  hand-labelled cases for its evaluator
    pack.py           WorkSource / Evaluator code, if needed
  tech-for-good/
  trading/
  osint/
```

### 4.1 `pack.yaml` (sketch)

```yaml
name: tech-for-good
version: 1
brief: brief.md
capabilities: [scout, assess, design, write]
currency: SIM                       # SIM for all simulated packs; USD only where real money flows
economy:
  funding: grant                    # market | grant | capital
  grant_per_cycle: 40000            # µcr into the treasury each cycle (from owner capital when live)
  treasury_reserve: 2000000
work_source:
  kind: briefs                      # templates | briefs | feed | self-directed (ventures, built 26 Sep)
  path: jobs.yaml
evaluator:
  kind: panel                       # llm | panel | deterministic | human | composite
  rubric_style: impact
  settle: on_review                 # immediate | on_review | after_horizon
member_tools: [web_search, web_fetch, read_archive]
policy:
  gate: [publish, contact_person, spend]
  forbidden: [create_accounts, contact_minors, collect_personal_data]
  egress: [allowlist.txt]
params:                             # overrides of kernel defaults
  job_reward: 60000
  deliver_ttl: 6
scorecard:                          # mission metrics: the headline of this society (§5b)
  - {name: useful_assessments, by: human_sample, target: rising}
  - {name: evidence_quality, by: code+grader, target: ">= 0.8"}
  - {name: cost_per_useful_assessment, by: code, target: falling}
dashboard:
  kpis: [assessments_accepted, avg_impact_score, cost_per_accepted_assessment]
```

### 4.2 The code interfaces

```python
class WorkSource(Protocol):
    def post(self, cycle: int, rng) -> list[Job]: ...          # new work this cycle (may be none)

class Evaluator(Protocol):
    def evaluate(self, job: Job) -> Verdict: ...               # may defer: Verdict(pending=True, settle_at=…)
    def settle(self, job: Job, cycle: int) -> Verdict | None: ...  # called later for deferred outcomes

@dataclass
class Verdict:
    score: float              # 0..1 quality
    value: int                # µcr the work is worth (may scale with score; 0 if it failed)
    reason: str
    pending: bool = False     # outcome not known yet (trading P&L, OSINT verification)
    settle_at: int | None = None
    cost: int = 0; model: str | None = None; usage: Usage | None = None; real: bool = False

class MemberTool(Protocol):
    name: str; description: str; input_schema: dict
    gated: bool               # True = needs a gate approval before it runs
    def run(self, args: dict, ctx: ToolContext) -> str: ...

@dataclass
class Pack:
    name: str; brief: str; capabilities: tuple[str, ...]
    work_source: WorkSource; evaluator: Evaluator
    member_tools: list[MemberTool]; policy: Policy
    params: dict; economy: Economy; calibration: list[Case]
```

Three generalisations the kernel needs for these to work:

1. **Deferred settlement.** Today a job is graded and paid at once. Trading P&L and OSINT
   verification are only known later. A job gets a `pending` state: the reward is escrowed until the
   evaluator settles, and reputation updates at settlement too.
2. **Value scales with quality.** Today it's pass/fail at 0.5. A pack can pay by score (a better
   assessment earns more), which rewards effectiveness rather than bare compliance.
3. **Funding models.** "Earn online" is a market economy: outside revenue pays for thinking.
   Tech-for-good and OSINT have no buyer, so they are **grant economies**: a fixed budget flows into
   the treasury, and co-ops earn it by producing work the evaluator values. Trading is a **capital
   economy**: co-ops are allocated notional capital, and their P&L (risk-adjusted) is their earning.
   The kernel's ledger already supports all three. Only the source of the credits changes.

---

## 5. Passing in context and spawning co-ops

### 5.1 Layers of context, and where each lives

| Layer | Example | Where it goes | Cost profile |
|---|---|---|---|
| **Kernel preamble** | how contracts, money and reputation work | every steward's system prompt, block 1 | cached across all co-ops and all societies |
| **Society brief** | "Find and assess tech-for-good initiatives in water access…" | system prompt, block 2 | cached across all co-ops in the society |
| **Co-op charter + doctrine** | "Momentum on large-cap equities, 1–4 week horizon, max 5% per position" | system prompt, block 3 | cached across that co-op's turns |
| **Observation** | this cycle's jobs, contracts, events | the user message, last | never cached (changes each turn) |
| **Reference material** | reports, datasets, prior research, your notes | a searchable **archive**, via a `read_archive` tool | paid only when an agent actually looks something up |
| **Seed playbooks** | methods you already trust | the library at genesis | used and cited like any playbook |

The rule: **small and stable goes in the prompt; large or occasionally needed goes in the archive.**
Stuffing documents into the prompt makes every call of every turn pay for them.

### 5.2 Founding: from a brief to co-ops (built in K3)

```
uv run python -m sim.found tech-for-good --pack earn_online --brief brief.md --context ./material/ --coops 4 \
    --backend lmstudio --model <id>
uv run python -m sim.found tech-for-good --approve
uv run python -m sim.live --society tech-for-good --backend lmstudio --model <id>
```

As built: blueprints are TOML (`blueprints.toml`, `approved = false` until you approve), there is no starting purse per
co-op yet (the pack's `purse_seed` applies), and "own ledger, bus, workspace" means a fresh world per run with its files
under `societies/<name>/runs/`. See `society.example/`.

1. **You write a brief**: purpose, what good looks like, what's off limits. For trading you also
   list the strategies you want tried, one per co-op.
2. **A founding call drafts blueprints.** One model call reads the brief and the pack, and proposes N
   co-ops. Each blueprint has a name, a charter, a doctrine, capabilities that complement the others,
   a member count and a starting purse. If you supplied doctrines (trading strategies), it uses them
   verbatim and only fills in the rest.
3. **You approve or edit** the blueprints (a file you can edit, or a screen in the console). Nothing
   starts without this. It is the constitution moment, and it is human.
4. **Genesis:** the society is created with its own ledger, bus namespace, workspace and run folder.
   The archive is indexed, seed playbooks go into the library, and co-ops are funded.
5. **From then on, no one is in charge.** The founding step never runs again inside the society. New
   co-ops appear only through the kernel's own mechanisms: spawn (needs a second), fork, merge.

The founder is a one-off drafting tool, not a coordinator. This keeps the project's central
principle (no orchestrator, no root agent) intact.

### 5.3 Blueprint (sketch)

```yaml
- name: momentum-desk
  charter: "Profit from persistent trends in liquid large-cap equities."
  doctrine: |
    Momentum, 1–4 week holding period, top-decile 12-1 month returns, rebalance weekly.
    Max 5% of capital per position, stop at -8%. No leverage.
  capabilities: [signal, execution]
  members: 3
  purse: 150000
```

---

## 5b. Measuring success beyond money

*Added 26 Sep at your request: tech-for-good and OSINT societies need measures of success other than money.*

### Fuel and mission are different things

In every society, **credits are fuel**: they pay for thinking, and they drive selection (a co-op that
wastes them goes quiet). But for a society whose purpose isn't profit, credits say nothing about
whether it is *succeeding*. So each pack declares a **scorecard**: the mission metrics that define
success for that society.

- The scorecard is the **headline** of that society's dashboard. Credits sit below it, as operations.
- The scorecard also **feeds the evaluator.** What a piece of work earns is set by how much it moves the
  scorecard. That keeps fuel and mission pointing the same way. If credits and the scorecard diverge,
  agents will chase credits (Goodhart's law), so the link is structural, not a hope.
- Some metrics are **measured by code** (citation validity, duplicates, costs), some by **graders**
  (quality against a rubric), and some **only by you** (usefulness, whether you acted on it). Metrics
  you rate are sampled, so reviewing stays light.
- Each metric states its direction, its target, and whether it's a **hard floor** (for example, zero
  ethics violations) rather than something to maximise.

### Tech-for-good scorecard (proposal)

| Metric | What it measures | Measured by |
|---|---|---|
| Useful assessments | Assessments you rate "useful" or better | You (sampled) |
| Acted on | Findings that led to a real follow-up (you contacted, funded, shared, built) | You |
| Evidence quality | Share of claims backed by a cited, checkable source | Code + grader |
| Feasibility realism | Cost, time and risk estimates judged plausible | Grader panel |
| Who benefits | Clarity and size of the benefiting group, with the estimate's basis | Grader panel |
| Coverage | Distinct problem areas and regions covered, not the same thing repeated | Code |
| Novelty | Share of initiatives not already in the library (no duplicates) | Code |
| Follow-up accuracy | When revisited later, did the initiative look as assessed? | Grader + you |
| Cost per useful assessment | Credits of thinking per assessment you rated useful | Code |
| Harms flagged | Risks and downsides identified, not just upside | Grader panel |

### OSINT scorecard (proposal)

| Metric | What it measures | Measured by |
|---|---|---|
| Verified claims | Share of claims independently verified by the verify co-op | Code + verify co-op |
| Citation validity | Cited sources exist, are reachable, and say what's claimed | Code + grader |
| Source independence | Claims corroborated by independent sources, not one source repeated | Grader |
| Confidence calibration | Stated confidence matches later outcomes (Brier score over resolved claims) | Code |
| Corrections | Claims later retracted or corrected (lower is better; honesty about it is rewarded) | Code |
| Questions answered | Investigation questions answered fully, partly, or not | You + grader |
| Usefulness | Findings you rate useful | You (sampled) |
| Cost per verified claim | Credits of thinking per verified claim | Code |
| **Ethics violations** | Any targeting of a private individual, personal-data aggregation, non-passive collection | Tool layer + audit. **Hard floor: must be zero; any violation pauses the society** |

### General metrics, every society

Efficiency (value per unit of thought), waste (calls with no action, refused tool calls, unused
drafts), cooperation health (share of work done through contracts, royalties crossing co-ops) and
concentration (how much work flows to the top co-op; the plan's Failure 2).

---

## 6. Principle: effectiveness and efficiency, not speed

The current engine rewards being first in several ways. The plan removes each, and adds
measurements that make efficiency visible and rewarded.

### 6.1 What rewards speed today, and what replaces it

| Today | Problem | Change |
|---|---|---|
| First community to call `claim` gets the job (random turn order) | Races, and hoarding: one LLM claimed 5 jobs in a turn | **Proposals, then allocation.** During a cycle co-ops *propose* for jobs (plan, price, confidence). At cycle end, allocation picks on reputation, fit and price, with a **claim bond** lost if the job fails |
| Pass/fail at 0.5 | "Good enough, fast" earns the same as excellent | **Value scales with quality**, and deferred outcomes settle later (§4.2) |
| Tight deadlines in cycles (deliver 3, review 2) | Pressure to act before thinking | **Pack-set deadlines**, generous where quality needs time. Deadlines exist to stop stalling, not to force haste |
| Cycles run as fast as the machine allows | Wall-clock pressure; no batching | **Cycles are logical time.** A society can run on a schedule (hourly, daily) and use the cheap slow path (below) |
| Thinking cost is invisible to the agent until the purse drops | No sense of efficiency | **Efficiency shown and scored** (below) |

### 6.2 Measuring efficiency

- **Value per unit of thought:** value earned ÷ compute spent, per co-op and per society, as a
  headline dashboard metric. It's in the observation too, so a steward sees its own ratio.
- **Cost per accepted piece of work**, per capability.
- **Waste:** calls that produced no action; tool calls refused; drafts never used.
- Efficiency should feed the economy, not just the dashboard. A co-op that produces the same value
  for less thinking keeps more of its purse. It then out-survives and can spawn. That is selection
  pressure towards efficiency, which is the plan's original compute-as-cost idea made visible.

### 6.3 Slow is also cheap

Because no one is racing:
- **Message Batches:** Anthropic's batch API processes requests asynchronously at about **50% of the
  price**. Steward turns that don't need an answer within seconds can go through batches.
- **Longer cache lifetime:** the stable prefix (kernel preamble + brief + charter) is cached, and a
  longer cache TTL suits slow cycles.
- **Deliberate before acting:** a co-op can spend a turn reading the archive and writing a plan into
  its journal, then act next turn. The generous deadlines make that affordable.
- **Local models where they're good enough:** graders and members can run locally when their
  calibration passes, and stewards use the stronger model.

---

## 7. Four societies, sketched

### 7.1 Earn online (pack 0, today's society)
- **Work:** the mock market now; real channels in Phase 2 (digital products, storefront, Stripe).
- **Evaluator:** LLM grader (calibrated), then real customers.
- **Economy:** market. The only pack that touches real money (USD) in its live form.
- **Tools:** web research; storefront listing (gated).

### 7.2 Trading (each co-op with its own strategy)
- **Capabilities:** `research` (fundamentals, news), `signal` (turns doctrine into trade ideas),
  `risk` (position sizing, exposure, veto), `execution` (orders against the paper broker).
- **Work:** mostly self-directed. Each co-op runs its doctrine each cycle. The contract-net carries
  trade between co-ops: a momentum desk buys a risk review from the risk co-op, or a research note
  from the research co-op.
- **Evaluator:** **deterministic, not an LLM.** Realised and marked-to-market P&L from a paper broker
  over a horizon, risk-adjusted (Sharpe or Sortino, max drawdown, turnover cost). Settled after the
  horizon, so this pack depends on deferred settlement.
- **Economy:** capital. Each co-op gets notional capital. Its earnings are risk-adjusted performance
  converted to credits, which pay for its thinking. A strategy that loses runs out of thinking budget
  and goes quiet. Selection happens by construction.
- **Tools:** market data feed (prices, fundamentals), paper broker (orders, positions), news search.
- **The path to real money** (your aim: real trading after extensive testing, with very low amounts
  and stop-losses). Each stage has to be passed before the next, and any stage can send a strategy back:

  | Stage | What runs | Money | Graduates when |
  |---|---|---|---|
  | 1. Paper, forward | Paper broker, live prices, modelled fees and slippage | SIM credits | A strategy beats its benchmark after costs, risk-adjusted, over a long window you set in advance (for example 3 months), with drawdown inside its limit |
  | 2. Shadow | Every order it would place is logged and priced against real fills, still on paper | SIM credits | Shadow and paper results agree within a tolerance; the risk limits never fired unexpectedly |
  | 3. Micro-live | A real broker account, behind the gate, with **very small amounts** | USD | Kept only while it stays inside every limit below; any breach sends it back to paper |

- **Limits for micro-live, enforced by code in the execution tool and the broker account itself, never
  by prompts:**
  - a **stop-loss on every position**, placed with the order, not afterwards
  - a small **per-position size cap** and **per-co-op capital cap** (tens of dollars, not hundreds, to start)
  - **daily and total loss limits** per co-op and for the society; hitting one closes positions and
    pauses trading
  - **no leverage, no margin, no shorting, no derivatives** at first
  - the **real-dollar kill-switch** covers trading losses as well as API spend
  - every order in stage 3 goes through the **gate**; batch approval is fine, silent autonomy isn't
  - a **kill criterion decided before going live** (for example: stop if down 20% of allocated capital
    or behind the benchmark after N months)
- **Other hard rules:**
  - **Forward testing only, no LLM backtests.** Models have read history. A "backtest" on past data
    tests the model's memory, not the strategy. Evaluate only on data after the run starts.
  - Your own account and money only. Check the tax and regulatory side before stage 3.
  - Not financial advice.

### 7.3 Tech-for-good

*Built in K4 (28 Sep) as `packs/tech_for_good/`. As built: work comes from subjects (your `questions.md`), the panel
is one model read through three lenses (evidence, usefulness, harm) rather than graders from other co-ops, you rate a
sample from the command line, and evidence is the archive or marked (unverified) until K5 brings the web. Novelty,
feasibility realism and follow-up accuracy from §5b are not measured yet.*
- **Capabilities:** `scout` (find initiatives, gaps, needs), `assess` (evidence, feasibility,
  impact), `design` (interventions, prototypes), `write` (briefs, proposals).
- **Work:** briefs you post (questions or areas), plus self-directed scouting jobs that co-ops propose
  and a small review panel approves.
- **Evaluator:** a composite. An LLM panel (graders from co-ops with no stake in the job) scores
  against an impact rubric: evidence quality, feasibility, who benefits, cost, risks. **You review a
  sample,** and your review settles disputed or high-value work.
- **Economy:** grant. A fixed budget per cycle is shared by what the evaluator values.
- **Tools:** web search and fetch, the archive.
- **Output:** a growing library of assessed initiatives and proposals, which the playbooks and
  royalties make cumulative.

### 7.4 OSINT
- **Capabilities:** `collect` (find public sources), `verify` (corroborate, date, geolocate,
  check provenance), `analyse` (connect, assess confidence), `report` (write findings with citations).
- **Work:** investigation questions you post, about organisations, events, infrastructure and public
  records.
- **Evaluator:** sourcing-first. Every claim must cite a source. A `verify` co-op, not the author,
  checks citations. The grader scores corroboration and confidence calibration, not how impressive the
  story is. Settlement is deferred until verification completes.
- **Economy:** grant.
- **Tools:** web search and fetch (read-only, allowlisted), archive, citation checker.
- **Hard rules (policy, enforced by the gate and the tool layer, not by prompts):**
  - **No targeting of private individuals.** Subjects are organisations, events and public-interest
    matters. No aggregating personal data about a person, no doxxing, no locating people.
  - **Passive collection only:** no accounts, no contacting anyone, no social engineering, no access
    to anything not public. Respect site terms and robots rules.
  - Anything that contacts a human, or publishes, is gated.
  - Legal and ethical review of the brief before founding.

---

## 8. Running several societies

- **Isolation:** each society has its own ledger file, bus namespace (a Redis key prefix, or a
  separate in-memory bus), workspaces and `runs/<society>/<run>/` folder. No money, reputation or
  messages cross between societies. Cross-society trade is a possible later "federation" over A2A,
  and out of scope here.
- **One registry:** `societies/` lists instances: `commons list`, `commons run <society> --cycles N`,
  `commons pause|resume <society>`.
- **Dashboard:** a society picker at the top; the same panels for each, plus the pack's KPIs.
- **Your machine:** the resource guardrails still apply. Societies run **one at a time**, or take turns
  on a schedule. That suits the slow tempo: a society can run a cycle an hour and sit idle between.
  Two societies should never each load their own local model.
- **Model backends are shared**, not per society: one LM Studio server or one Anthropic client, with
  spend attributed per society and a real-dollar kill-switch per society *and* in total.

---

## 9. How we get there from today's code

The trap to avoid is designing the abstraction from one example. The plan extracts the kernel
while keeping today's society working, then lets the **second** pack show where the seams really
are, before building the harder ones.

| Step | What | Done when |
|---|---|---|
| **K1** Kernel/pack split | Move the market, capabilities, job templates, grader choice, preamble market section, seed population and param defaults into `packs/earn-online/`. Add `Pack`, `WorkSource`, `Evaluator` interfaces and a `Society` object that builds a `World` from a pack | Every existing test passes with pack 0 loaded; `grep` finds no domain words in the kernel |
| **K2** Tempo and efficiency | Proposals-then-allocation with a claim bond (fixes hoarding); value scaled by quality; deferred settlement with escrow; efficiency metrics in the observation and dashboard; pack-set deadlines | The acceptance suite still passes; a test shows hoarding is unprofitable; the efficiency panel is live |
| **K3** Context and founding (operator directives, context and limits built early as 1.7) | Brief and charter/doctrine as cached system blocks; the archive and `read_archive`; `commons found` with blueprint drafting and approval; per-society isolation and `runs/` layout | A society is founded from a brief file and runs, with blueprints approved by you |
| **K4** Second pack: tech-for-good | Grant economy; brief-based work source; composite evaluator with a panel and a human sample; the **scorecard** (§5b) as the dashboard headline and an input to the evaluator; calibration set | Runs alongside earn-online (not at the same time) with no kernel changes beyond bug fixes |
| **K5** Member tools and the gate | Tool-using members (web search/fetch, archive), with the gate enforced in the tool layer plus an egress allowlist; batch approval in the console | A gated tool can't run without approval, proven by test |
| **K6** Trading pack | Paper broker; market data; deterministic, deferred, risk-adjusted evaluator; capital economy; doctrine per co-op; stop-losses and loss limits in the execution tool from day one | Stage 1 running: 30+ forward cycles on paper, with performance settled per horizon. Stages 2–3 (shadow, micro-live) are separate decisions after the graduation criteria are met |
| **K7** OSINT pack | Sourcing-first evaluator; `verify` as a separate co-op; policy with forbidden-target rules enforced in tools | Red-team test: a brief targeting a private individual is refused at founding, and a tool call aimed at one is blocked |
| **K8** Many societies | Registry, CLI, dashboard picker, per-society and total spend caps, a scheduler for slow cadences | Two societies run on alternate schedules on one machine within the guardrails |

K1–K3 are refactoring plus the tempo changes; they make the current work better regardless of domain.
K4 is the real test of the design. K6 and K7 carry the most risk and come last on purpose.

---

## 10. Pitfalls, and how the plan handles them

- **Abstracting too early.** Designing interfaces from one example produces the wrong seams. *Answer:*
  pack 0 first with no behaviour change, then a deliberately different second pack (tech-for-good:
  no market, no money) before trading and OSINT.
- **The evaluator is the whole game.** Every society optimises towards its evaluator, and a bad one
  gets gamed (Goodhart's law). *Answer:* every pack ships a calibration set and must pass it, like the
  grader did in 1.3. Evaluators that can be deterministic are (trading). Judged work gets panels and a
  human sample. Audits and disputes stay.
- **Deferred outcomes blur credit.** When P&L or verification arrives cycles later, who gets credit
  and when does reputation move? *Answer:* escrow and settle at the horizon. Reputation updates at
  settlement, and citations recorded at the time of work decide royalties.
- **Context cost creep.** Big briefs make every call expensive. *Answer:* the layers in §5.1: short
  briefs in the prompt, everything else in the archive, and prompt size shown on the dashboard.
- **Grant economies can starve or bloat.** With no market, the grant size *is* the economy. *Answer:*
  a grant-per-cycle setting, the treasury reserve rule, and the efficiency metrics to tune it.
- **LLM trading is easy to fool yourself with.** Look-ahead bias, backtests contaminated by training
  data, overfitting to noise, ignoring costs. *Answer:* forward-only paper trading, transaction costs
  in the evaluator, long horizons, and a kill criterion decided before starting.
- **OSINT can harm people.** Aggregating public data about individuals is doxxing, however public each
  piece is. *Answer:* forbidden targets are policy, enforced in founding and in the tool layer, not
  merely stated in prompts; passive collection only; human review of briefs.
- **Model capability limits.** The 1.5 smoke run showed small local models can't yet trade in this
  kernel. Richer domains need stronger stewards. *Answer:* strong stewards, cheaper members and
  graders where calibration allows, and batches for the slow path.
- **Resource limits on one Mac.** *Answer:* one society at a time, scheduled cadence, shared model
  backend, the existing guardrails.
- **"Slow" can become "stuck."** Generous deadlines invite procrastination. *Answer:* deadlines still
  exist and expire; upkeep still charges idle members; the efficiency metric exposes idle thinking.

---

## 11. Changes to the roadmap

Recommended order:

1. **Finish a minimal 1.5:** one capable steward model actually trading on the mock market, either
   locally (Qwen 3.5 35B-A3B) or via Anthropic under a spend cap, so the kernel is proven with real
   agents before it's generalised.
2. **K1–K3** (kernel extraction, tempo and efficiency, context and founding). These also resolve two
   open 1.5 findings: claim hoarding (K2's bond and allocation) and reward calibration (K2's
   quality-scaled value and efficiency metrics).
3. **K4** tech-for-good, then **K5** member tools and the gate.
4. **Phase 2** (the real earn-online channel) becomes pack 0's live mode. It needs K5's gate anyway.
5. **K6** trading (paper), **K7** OSINT, **K8** many societies.

Phase 1's original done-when (unscripted spawn, fork and cross-community royalty) still stands, and
can be met in any pack.

---

## 12. Decisions for you

1. **Which pack goes second?** I recommend **tech-for-good**: no real money, no market, low harm, and
   different enough from earn-online to test the abstraction. Trading is the most exciting and the
   most risky; OSINT needs the strongest guardrails.
2. **Finish 1.5 first, or start K1 now?** I recommend a minimal 1.5 first (one capable model trading
   on the mock market). Otherwise we'd be generalising a kernel no real agent has used yet. That
   needs your choice between Qwen 35B locally (22 GB, over the guardrail) and Anthropic (real spend).
3. **Founding: model-drafted blueprints with your approval, or hand-written only?** I recommend
   drafted and approved: fast, and you remain the constitution.
4. **Trading scope.** *Partly answered 26 Sep:* real money eventually, after extensive testing, with very
   small amounts and stop-losses (the staged path in §7.2). Still open: which markets (equities, crypto,
   FX), which data source and broker, the graduation window, and the exact caps.
5. **Scorecards.** The tech-for-good and OSINT scorecards in §5b are proposals. Which metrics matter
   most to you, and how much rating are you willing to do (the "you" rows)?
6. **OSINT scope.** The forbidden-target rules in §7.4 are my proposal. What subjects do you actually
   want investigated? This decides the allowlists and the evaluator.
7. **Tempo.** What cadence feels right for a real society: a cycle an hour, a day? This drives batch
   usage and cost.
