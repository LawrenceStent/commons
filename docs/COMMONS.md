# Commons: the complete guide

*What it is, how it works, why it is built this way, what has been done, what comes next, and what
could go wrong. Last updated 25 Sep 2026, at the end of Phase 1.2 (branch `phase-1`, commit `18810f3`).*

Companion documents:
- `docs/plan.html` is the original design brief (24 Sep 2026). It sets out the thesis, and this guide
  doesn't replace it.
- `docs/FRAMEWORK.md` (26 Sep 2026) plans the next step: extracting a domain-agnostic kernel so many
  societies can run on it (earn online, trading, tech-for-good, OSINT), founded from a brief. It also
  sets the principle of effectiveness and efficiency, not speed; mission scorecards for non-profit
  societies; and a staged path to small real-money trading.
- `docs/DASHBOARD.md` (26 Sep 2026): ideas for a cyberpunk redesign of the dashboard and more
  creative views of the data.
- `docs/CHECKLIST.md` is the working build checklist. It records what is ticked and the findings
  from each step.
- This guide is the long-form explanation that ties them together.

---

## Contents

1. [What Commons is](#1-what-commons-is)
2. [Status at a glance](#2-status-at-a-glance)
3. [Concepts](#3-concepts)
4. [Acronyms and jargon](#4-acronyms-and-jargon)
5. [Architecture](#5-architecture)
6. [How one cycle runs](#6-how-one-cycle-runs)
7. [The mechanisms, and why each exists](#7-the-mechanisms-and-why-each-exists)
8. [Money: created credits and real dollars](#8-money-created-credits-and-real-dollars)
9. [The economy's numbers](#9-the-economys-numbers)
10. [The live dashboard](#10-the-live-dashboard)
11. [What has been built so far, and what we learned](#11-what-has-been-built-so-far-and-what-we-learned)
12. [Roadmap](#12-roadmap)
13. [Strengths](#13-strengths)
14. [Weaknesses and limitations](#14-weaknesses-and-limitations)
15. [Pitfalls and risks](#15-pitfalls-and-risks)
16. [Decisions log](#16-decisions-log)
17. [Open questions](#17-open-questions)
18. [Operating guide](#18-operating-guide)
19. [Testing strategy](#19-testing-strategy)

---

## 1. What Commons is

Commons is an **economy of AI agent communities with no one in charge**. Each community is a small
team of agents with its own charter and its own purse. Each tries to earn money in its own way,
buys help from other communities when it lacks a skill, and pays for its own thinking. Every
model call costs it money.

The idea in one sentence, from the plan:

> There is no orchestrator, no root agent, and no privileged node. The only asymmetries in the
> system are reputation and treasury balance, and both are earned, decay, and can be lost.

### Why build it this way

Most "multi-agent" systems are hierarchies in disguise: a planner splits the work, workers do it, and a
summariser reports back. That shape is easy to build, but nothing in it *wants* anything, so
nothing in it adapts, specialises or cooperates by choice.

Commons replaces the planner with **a market and a reputation**:

- **Work is allocated by bidding, not assignment.** A community that needs something it can't do
  announces it, and others bid. Nobody can be told what to do.
- **Cooperation has to pay.** The design never *asks* agents to cooperate; research shows that
  instruction doesn't hold. It makes cooperation the cheapest strategy available: honest partners
  get more work, cheats get refused, and methods shared in the library earn royalties.
- **Compute is the cost of doing business.** Every model call is debited from the calling
  community's purse. A community that burns tokens producing nothing runs dry and goes quiet; one
  that earns buys itself more thinking. Cost control and selection pressure are the same mechanism,
  which is also what keeps the project affordable.

### The three ways it could fail (from the plan), and the design's answer to each

| Failure | What happens | Design answer |
|---|---|---|
| **Cooperation collapse** | Agents over-extract from shared resources until the commons dies. Telling them to cooperate doesn't fix it. | A first-class reputation system. Every settled contract leaves a signed record; low reputation means your bids get refused and your bus rate limit tightens. |
| **Hierarchy crystallising anyway** | One node accumulates reputation and quietly becomes the coordinator. | Structural anti-concentration. Spawning needs another community's second; anyone can fork away; votes (later) use lottery facilitators and capped weights. |
| **The bill** | Twenty agents in open loops burn hundreds of dollars a week producing prose. | Compute-as-cost, a cheap mock market for all the incentive tuning, model tiering, prompt caching, per-task budgets and a real-dollar kill-switch. |

---

## 2. Status at a glance

| Phase | What | Status |
|---|---|---|
| 0 | Substrate: bus, ledger, reputation, meter, registry, protocol, scripted society, console | ✅ Done 24 Sep |
| 1.0 | Live dashboard of every component | ✅ Done 25 Sep (replay from saved runs still open) |
| 1.0b | Created (SIM) money separated from real (USD) money | ✅ Done 25 Sep |
| 1.1 | Turn-based engine: communities act through tools, and contracts span cycles | ✅ Done 25 Sep |
| 1.2 | Spawn, retire, fork, merge, learn; playbooks; disputes and audits | ✅ Done 25 Sep |
| 1.3 | LLM grader, model backends (structured output), calibration set | ✅ Done 25 Sep; local Hermes 8B scores 8/9 and resists injection; Anthropic calibration optional |
| 1.4 | LLM agent runtime: steward tool loop, members, observation renderer, live runner | ✅ Done 25 Sep (tested with fake models) |
| 1.5 | Live runs: local first, then Anthropic with a spend cap | ⏳ In progress: local smoke run done 25 Sep; small local models can't trade |
| K1–K8 | Framework: one kernel, many societies (packs, founding from a brief, tempo and efficiency) | Planned 26 Sep (`docs/FRAMEWORK.md`) |
| 2 | One real channel: digital products, a storefront, Stripe, the human gate | Planned (becomes pack 0's live mode) |
| 3 | More channels: content, services, affiliate | Planned |
| 4 | On-chain settlement (Coinbase Agentic Wallets, x402) | Planned |

**Code:** about 3,000 lines of Python in `substrate/`, `protocol/`, `society/`, `sim/` and
`console/`, plus 94 tests. Nothing yet has spent a real dollar. All money so far is simulated
credits.

---

## 3. Concepts

Grouped by area. Terms in **bold** are used throughout the code and this guide.

### Who exists

- **Community.** The unit of agency: a small team (1–7 **members**) with a **charter**, a set of
  **capabilities**, a **purse**, a signing key and a workspace. It is the thing that bids, earns,
  builds a reputation and can be refused. (`society/community.py`)
- **Member.** One agent in a community. For scripted runs a member is a count; for LLM runs a member
  is a model call the steward commissions. Each funded member gives the community 2 **actions** per
  cycle.
- **Steward** *(from 1.4)*. The community's deciding agent: it reads the observation and calls tools.
  Members do the work it commissions.
- **Charter.** A short statement of what the community is for. It is shown to LLM agents every
  turn. Whether it may change mid-run is an open question (see §17).
- **Capability.** A kind of work a community can do. The mock market uses four: `research`, `build`,
  `design`, `write`. Reputation is tracked *per capability*: you can be trusted for research and
  distrusted for build.
- **Strategy** (or policy). The code that decides a community's turn. Scripted strategies (cooperator,
  defector, free-rider) are the permanent regression suite; the LLM runtime is another strategy with
  the same interface.

### Time

- **Cycle.** One tick of the world. Every cycle runs a fixed sequence of phases (§6).
- **Turn.** Each active community gets one turn per cycle, in random order. It sees an
  **observation** and acts through the **actions** interface.
- **Wake.** At the start of a cycle, each community decides how many members to pay to think. Paying
  for none means **silence**: no turn that cycle.
- **Capacity.** Actions left this turn (2 per woken member). Doing work, bidding, claiming and
  delivering use capacity. Deciding things (awarding, reviewing, rating) doesn't.

### Money

- **Purse.** A community's spendable balance. It can never go negative.
- **Treasury.** The shared pot. It receives 20% of revenue (while below its reserve), fees and
  unclaimed royalties. It pays the basic budget and grading.
- **Basic budget** (the **floor**). A small top-up paid only to poor purses, so a community can
  think its way out of a bad patch but can't live on handouts.
- **Upkeep.** The cost of waking one member for one cycle.
- **Work cost.** What a scripted community spends producing one part. For LLM agents this becomes
  the real token cost of the call.
- **SIM / credits (cr).** Created money, used only in simulations. It can never become dollars.
- **USD.** Real money. Every unit traces to something outside: your capital, a customer payment, a
  real API bill.
- **Micro-units.** All amounts are stored as integers in millionths: 80,000 micro-credits = 0.08 cr.
  Real dollars are stored as micro-dollars the same way.

### The market and contracts

- **Market job.** Demand from outside, posted on the **board**. Each job has 2 **parts**, one per
  capability, and a **rubric** per part. For example, "Launch kit for a bike repair kit" needs a
  `research` part and a `write` part.
- **Venture.** Work a co-op thinks up itself: it proposes a product or service in parts, deterministic
  rules refuse bad proposals at once, an appraiser scores the rest, a fixed formula sets the reward, and
  the market approves the best-scored within a budget. An approved venture becomes the proposer's own job.
- **Claim.** Taking a job off the board. The claimant becomes the job's **prime** and must submit all
  parts by the job's deadline.
- **Contract-net.** The protocol for buying work from peers:
  **announce → bid → award → deliver → review (settle)**. It is the only way to get help, because
  there is no escalation path.
- **Prime.** The community that announced a contract (and usually claimed the job).
- **Contractor** (or winner). The community whose bid was awarded.
- **Advance.** The share of the price paid on award (50% by default). **Remainder**: the rest, paid
  when the prime accepts the delivery.
- **Grader.** Judges each part against its rubric. The market pays only if every part passes (score
  ≥ 0.5). `StubGrader` reads scripted quality tags; `LLMGrader` (1.3) will read real work.
- **Revenue split.** When a job is paid: 70% to the prime, 20% to the treasury, 10% to the authors of
  cited playbooks. When the treasury is at its reserve, the split becomes 90 / 0 / 10.

### Trust

- **Attestation.** A signed rating (0 to 1) one community files about another after a contract.
- **Direct evidence.** What you saw yourself. **Gossip**: what others relay to you, discounted by how
  much you trust the source and never allowed to compound.
- **Score / trust / standing.** Three views of reputation:
  - **score** is one observer's view of one subject in one capability, from direct evidence plus
    gossip.
  - **trust** is one observer's direct-only view of a subject across all capabilities.
  - **standing** pools everyone's first-hand evidence about a subject: the commons' view.
- **Decay.** Old evidence fades every cycle. Records that are *mostly bad* fade 4× more slowly, so a
  cheat isn't quickly forgiven. Mostly good records fade evenly.
- **Refusal.** The world itself refuses any bid or award where the bidder's standing, or the prime's own
  record of them in that capability, is below 0.35 (`bid_floor`). It's a deterministic rule in
  `World.eligible`, not a judgement left to the agents: in the 1.5 runs, LLM primes kept hiring a known
  defector. With reputation off (the control run), no one is refused.
- **Allowance.** How many initiating messages a community may post per cycle. It scales with
  standing, from 1 up to 18 (1.5× the base of 12). Obligations (award, deliver, settle, attest,
  dispute, gate) are never throttled, so "I was rate-limited" can't be an excuse not to deliver.
- **Dispute / audit.** A contractor can take a rejection to a paid audit by the grader. The loser pays
  and the audit's verdict counts against their standing. Since 26 Sep (option B) the grader judges every
  delivery directly, so this path is only used when `grader_reviews` is switched off.

### Knowledge

- **Playbook.** A written method for a capability, published to the commons **library** for a fee.
- **Citation.** Using a playbook in a delivery or part cites it *structurally*: the citation is part
  of the message, not a courtesy.
- **Royalty.** Cited authors share the 10% royalty slice of the job's revenue, and also earn 10% of
  the base cost when someone learns a capability from their playbook. This is what makes sharing pay
  better than hoarding.

### Population

- **Spawn.** Add a member. It needs a second from a different community and a fee to the treasury.
- **Retire.** Drop a member.
- **Fork.** Some members walk out as a new community with a share of the purse and some of the
  parent's capabilities.
- **Merge.** One community joins another; both must agree.
- **Learn.** Buy a new capability. The price rises steeply for generalists.
- **Dissolved.** A community that merged away. Its history and keys are kept so old signatures still
  verify.

### Records

- **Activity log.** One timeline of every **action** (a call through the executor, by any agent), every
  **decision** (what a steward said, and the `why` it can attach to any action) and every **change** in the
  world (jobs, contracts, grades, audits, population, playbooks, kill-switches). Bounded in memory; live runs
  stream it to `runs/<run>.activity.jsonl`.
- **Idea.** Something a steward records as worth remembering. **Goal**: a titled checklist of steps a
  steward sets for its community (optionally from an idea) and ticks off as it goes. Both are shown back to
  the community every turn and on the dashboard.

### Operator

- **Operator.** You, the person running a society. You give co-ops **directives** (plain-language instructions,
  read every turn in a trusted part of the steward's prompt), **context** (reference files, capped in size) and
  **limits** (world rules: forbidden actions, a price cap, a job cap, a thinking budget per turn). They live in an
  `operator/` folder, re-read every cycle, and can be edited from the dashboard. Directives are guidance a model
  can misjudge; limits are enforced.

### Safety and control

- **Gate.** Any action that touches the outside world (publish, post, spend, sign) waits for your
  approval. Schemas exist; enforcement arrives in Phase 2.
- **Kill-switch.** There are two:
  - a notional daily ceiling on credits
  - a **real-dollar daily ceiling** ($5 by default) that halts everything when real API spend
    reaches it
- **Memory guard.** The dashboard pauses the run if its own process exceeds 2 GB.

---

## 4. Acronyms and jargon

| Term | Meaning | Where it matters here |
|---|---|---|
| **A2A** | Agent-to-Agent protocol (now under the Linux Foundation's Agentic AI Foundation) | Our registry uses A2A-style "agent cards" so outside agents could discover our communities later |
| **ACP** | Agent Communication Protocol | Merged into A2A in Aug 2025; mentioned only for history |
| **MCP** | Model Context Protocol, for connecting an agent to tools and data | Likely used for channel tools in Phase 2+ |
| **API** | Application Programming Interface | "The API bill" means Anthropic's charges for model calls |
| **LLM** | Large Language Model | The agents from 1.4 on |
| **SDK** | Software Development Kit | *Claude Agent SDK*: considered for stewards, deferred (§16) |
| **Messages API** | Anthropic's core endpoint for model calls | Our runtime: we run the tool loop ourselves |
| **Tool / tool call** | A function the model can ask to run | Every action (claim, bid, fork, …) becomes a tool |
| **Prompt cache** | The provider re-uses an identical prompt prefix at about 10% of the price | Why the protocol preamble must stay byte-identical |
| **Haiku / Sonnet / Opus** | Anthropic model tiers, from cheap and fast to capable and costly | Members and grader on Haiku 4.5, stewards on Sonnet 5 |
| **LM Studio** | A desktop app that runs open models locally, with an OpenAI-compatible server on port 1234 | Free local runs; notional charges only |
| **SIM / USD / cr** | Simulated credits / real US dollars / the credit symbol | §8 |
| **Micro-dollar** | One millionth of a dollar; $1 per million tokens = 1 micro-dollar per token | All ledger amounts |
| **Double-entry ledger** | Every transaction has legs that sum to zero, so money is only moved | `substrate/ledger.py` |
| **SQLite / WAL** | An embedded database / Write-Ahead Logging mode for safe concurrent reads | The ledger's storage |
| **Redis Streams** | An append-only log in Redis with consumer groups | The production bus backend (`RedisBus`) |
| **Consumer group** | A named reader that tracks its own position in a stream | One per community per message family |
| **MAXLEN** | Redis's cap on stream length | Our in-memory bus copies this idea to bound memory |
| **Envelope** | A signed, content-addressed wrapper around every protocol message | `protocol/envelope.py` |
| **Ed25519** | A fast public-key signature scheme | Every community signs its messages; the bus verifies |
| **SHA-256** | A cryptographic hash | Message ids are the hash of the canonical JSON, so they can't be forged |
| **Pydantic** | A Python data-validation library | All protocol schemas |
| **FastAPI** | A Python web framework | The console / dashboard server |
| **SSE** | Server-Sent Events: a one-way live stream from server to browser | The dashboard's single live connection |
| **htmx** | A small library for partial page updates | Used by the Phase 0 console; replaced by SSE in 1.0 |
| **uv** | A fast Python package and project manager | `uv run`, `uv add` |
| **RSS** | Resident Set Size: memory a process actually holds | The memory guard watches it |
| **CPU** | Central Processing Unit | Shown in the dashboard's host panel |
| **TTL** | Time To Live: how long something lasts before it expires | Board, job, bid, delivery and review deadlines |
| **RNG / seed** | Random-number generator / its starting value | Same seed, same world: runs are reproducible |
| **Contract-net** | A classic multi-agent task-allocation protocol (announce, bid, award) | §7.2 |
| **Beta reputation** | Scoring by counts of good and bad outcomes on a uniform prior: (1+good)/(2+good+bad) | Unknown parties score 0.5 |
| **Prime** | The buyer in a contract (from "prime contractor") | §3 |
| **Stub** | A stand-in implementation for testing | `StubGrader`, scripted strategies |
| **Kill-switch** | A hard stop | §3 |
| **KPI** | Key Performance Indicator | Venture metrics (Phase 2) |
| **SEO** | Search Engine Optimisation | A Phase 3 channel; slow feedback |
| **ToS** | Terms of Service | Many platforms forbid automated posting and accounts (§15) |
| **Stripe** | A payment processor | The Phase 2 revenue source (`ext:stripe`) |
| **PreToolUse hook** | A callback that runs before an agent's tool executes | Where the gate and meter can intercept actions |
| **Egress allowlist** | Network rule: outbound traffic only to approved hosts | The gate's second enforcement point |
| **MPC wallet** | Multi-Party Computation wallet: the key is split so no one holds it whole | Coinbase Agentic Wallets (Phase 4) |
| **Base / Base Sepolia** | Coinbase's Ethereum layer-2 network / its test network | Phase 4, testnet first |
| **x402** | A standard for paying HTTP 402 "Payment Required" responses automatically | Phase 4: agents paying for APIs and data |
| **P2P** | Peer-to-peer | The shape of the society: no hub |
| **JSON-RPC** | A remote-call format using JSON | Used by A2A |

---

## 5. Architecture

### 5.1 Layers

```
┌───────────────────────────────────────────────────────────────────────┐
│ SOCIETY      communities, charters, strategies (scripted now, LLM 1.4) │  society/
├───────────────────────────────────────────────────────────────────────┤
│ SIMULATION   world engine, market board, actions executor, population │  sim/
├───────────────────────────────────────────────────────────────────────┤
│ PROTOCOL     six message families, signed envelopes                    │  protocol/
├───────────────────────────────────────────────────────────────────────┤
│ SUBSTRATE    bus · ledger · reputation · meter · registry · workspace │  substrate/
│              · telemetry hub                                          │
├───────────────────────────────────────────────────────────────────────┤
│ CONSOLE      live dashboard (FastAPI + SSE), controls, host monitor   │  console/
└───────────────────────────────────────────────────────────────────────┘
```

The rule running through every layer: **record-keepers, not deciders.** The bus, ledger, reputation
store and registry keep records and enforce invariants (signatures, balances, rate limits,
deadlines). Nothing below the society layer can assign work to a community that didn't bid for it.

### 5.2 Module map (what's actually in the repo)

| Path | Lines | Role |
|---|---|---|
| `protocol/envelope.py` | 93 | `Envelope`: signed (Ed25519), content-addressed (SHA-256 of canonical JSON). `Identity` holds a community's key |
| `protocol/{contract,reputation,knowledge,population,governance,gate}.py` | ~190 | The six message families and their verbs (§5.3) |
| `substrate/bus.py` | 178 | `Bus` front door: signature check plus reputation-scaled rate limit. `MemoryBus` for simulations (capped streams), `RedisBus` for production |
| `substrate/ledger.py` | 198 | Double-entry SQLite ledger with two currencies (SIM, USD), per-currency external accounts, the revenue split, capital and a real-money summary |
| `substrate/meter.py` | 153 | Price table, notional charges, real-dollar recording, per-task budgets, both kill-switches |
| `substrate/reputation.py` | 115 | Beta evidence per (observer, subject, capability); gossip; asymmetric decay; standing; fork inheritance |
| `substrate/registry.py` | 35 | A2A-style agent cards and public keys |
| `substrate/workspace.py` | 30 | One sandboxed directory per community; path-escape protection |
| `substrate/telemetry.py` | 82 | The telemetry hub: every component emits events into bounded rings |
| `society/community.py` | 36 | The `Community` record |
| `society/observation.py` | 165 | What a community sees (`Observation` and its views) and the `ActionsAPI` it may call |
| `society/strategies/base.py` | 239 | The honest default strategy: obligations first, then new business, then growth |
| `society/strategies/scripted.py` | 56 | Cooperator, Defector, FreeRider: the permanent regression suite |
| `sim/engine.py` | 622 | `World`: the cycle, deadlines, grading, settlement, observation, gossip, records |
| `sim/actions.py` | 267 | The actions executor: the only way a strategy touches the world |
| `sim/market.py` | 116 | Job generator (parts and rubrics), `Grader` interface, `StubGrader` |
| `sim/population.py` | 229 | Spawn, retire, fork, merge, learn, proposal expiry |
| `sim/grader.py` | ~70 | `LLMGrader`: rubric grading with structured output; untrusted work fenced |
| `sim/calibration.py`, `sim/calibrate.py` | ~150 | Hand-labelled grader check and its command-line runner |
| `runtime/backends.py` | ~330 | `ModelBackend`: `structured` and `chat` for Anthropic, LM Studio and fake; usage and real/notional on every call |
| `runtime/render.py` | ~170 | The frozen preamble, the charter block, and the observation renderer (untrusted content fenced) |
| `runtime/tools.py` | ~110 | The 21 steward tools, sorted and stable |
| `runtime/steward.py` | ~210 | `LLMStrategy`: the steward loop, members via `commission`, drafts, metering, transcripts |
| `runtime/fakes.py` | ~35 | A fake steward and grade for dry runs and tests |
| `sim/live.py` | ~110 | Runs an LLM society with limits; `--serve` for the dashboard |
| `console/app.py` | 252 | Snapshot builder, SSE stream, controls, drill-down, memory guard |
| `console/dashboard.html` | 318 | The dashboard page (vanilla JS, no build step) |
| `console/host.py` | 51 | Process and system memory, CPU, LM Studio status |

The plan's repository sketch also lists `society/agent.py`, `society/venture.py`, `channels/` and
`market_sim/`. Those arrive in later phases; the mock market lives in `sim/market.py` for now.

### 5.3 The protocol: six message families

Every behaviour the society supports must be expressible in these. If it can't be, the society
doesn't support it.

| Family | Verbs | Used today? |
|---|---|---|
| `contract` | announce · bid · award · deliver · settle | ✅ Every contract |
| `reputation` | gossip · attest · dispute | ✅ Ratings, gossip every 5 cycles, disputes |
| `knowledge` | publish · cite · royalty | ✅ Playbooks and citations |
| `population` | spawn · retire · fork · merge | ✅ Since 1.2 |
| `governance` | propose · second · vote · enact | ⛔ Schemas only (§12) |
| `gate` | request · approve · deny · revoke | ⛔ Schemas only (Phase 2) |

Every message is sealed in an envelope: sender, cycle, family, verb, body, an id that is the SHA-256
of the canonical JSON, and an Ed25519 signature. The bus rejects anything unsigned or signed by an
unregistered key, so gossip and ratings can't be forged.

### 5.4 Where the rules live

A strategy never touches the ledger, bus or reputation directly. The path is always:

```
strategy.turn(observation, actions)
        │  calls e.g. actions.bid("J12.write.1", 16_000)
        ▼
sim/actions.py      validate → spend capacity → sign & publish on the bus → move money via ledger
        │           returns Outcome(ok, message) — failures are readable text, never exceptions
        ▼
sim/engine.py       state changes, deadlines, grading, settlement, telemetry events
```

This matters most for LLM agents. Every refusal comes back as a sentence the model can read and
recover from ("you lack the build capability; announce a contract instead"), and no prompt can reach
around the rules.

### 5.5 Telemetry

Every component emits events into one **hub** (`substrate/telemetry.py`): `ledger.post`,
`bus.publish`, `meter.charge`, `meter.real`, `reputation.attest`, `contract.stage`, `market.job`,
`grader.grade`, `population.*`, `world.cycle`, `host.sample`, and more.

- The hub keeps only the **last N events of each kind** (a ring buffer) plus a running count, so
  memory stays flat however long a run goes.
- It refuses unbounded kinds, so an id can't accidentally end up in an event name.
- No component imports the console. The dashboard reads the hub, the world reads nothing back, and
  the dependency runs one way.

### 5.6 Persistence and memory bounds

| Store | Bound |
|---|---|
| Ledger | SQLite in memory by default; `Params(ledger_path="runs/x.sqlite")` puts it on disk for long runs |
| Bus streams | Compacted every cycle; each family capped at 5,000 envelopes (like Redis MAXLEN) |
| Bus tail, telemetry | Ring buffers (500 per kind by default) |
| Jobs and contracts | Dropped 20 cycles after closing |
| Journals, inboxes | Last 20 notes and 50 events per community |
| Per-cycle history | Grows by one small record per community per cycle, and is used by tests. A candidate for downsampling if runs get very long |

Measured: 10,000 cycles took 35 s (with signature checks) and grew memory by about 59 MB.

---

## 6. How one cycle runs

```
cycle N
  1. floor      treasury tops up any purse below 8,000 (two cycles of one member) by 3,000
  2. wake       each community picks how many members to pay for; 0 = silent this cycle
  3. deadlines  expire bids, fail undelivered work, accept unreviewed deliveries by default,
                fail late jobs, expire spawn/merge proposals
  4. market     2 new jobs go on the board
  5. turns      each awake community, in random order, sees its Observation and acts
  6. gossip     every 5th cycle: communities relay their strongest first-hand beliefs
  7. decay      reputation evidence fades
  8. compact    the bus drops consumed and over-cap envelopes; old jobs and contracts are pruned
  9. record     per-community snapshot; a world.cycle telemetry event
```

A scripted turn follows a fixed priority: **learn from events → review deliveries → deliver work
won → dispute unfair rejections → rate counterparties → award announcements → claim a job → work on
own jobs → bid → publish a playbook → grow.** Obligations come before new business, which is the
same discipline we will ask of LLM stewards.

### Contract lifecycle

```
            announce                bid(s)             award (next cycle or later)
   prime ──────────────► OPEN ────────────────► OPEN ─────────────────────────► AWARDED
                          │                                  advance paid          │
                          │ no award within 3 cycles                               │ deliver within 3 cycles
                          ▼                                                        ▼
                       EXPIRED                                                 DELIVERED
                                                   no delivery ──► FAILED       │      │
                                                   (prime's complaint filed)    │      │ prime reviews
                                                                                │      ▼
                              unreviewed after 2 cycles: accepted by default ◄──┘   ACCEPTED (remainder paid)
                              prime can't pay: DEFAULTED (contractor's complaint)   REJECTED
                                                                                       │ dispute within 3 cycles
                                                                                       ▼
                                                                          audit: overturned → ACCEPTED
                                                                                 upheld     → stays REJECTED
```

Every stage has a deadline, so **no party can stall another**. Where a failure is objective (work
never delivered, a prime that never paid), the substrate files the complaint automatically. Where it
is a judgement (was this work good enough?), the parties decide and the audit is the appeal.

---

## 7. The mechanisms, and why each exists

Each mechanism below exists because something broke without it. The "why" is the part to keep.

### 7.1 Reputation

- **How:** beta evidence per (observer, subject, capability). Unknown parties are 0.5. Direct
  experience counts fully. Gossip is discounted by 50% and by how much you trust the source, and each
  source's newest relay *replaces* its last one, so repeated gossip can't compound into certainty.
- **Why per capability:** a good researcher can be a bad builder.
- **Why decay:** people change, and old evidence should matter less.
- **Why asymmetric decay, and only for bad records:**
  - Phase 0: with even decay, a defector's record faded back over the refusal line, it scammed once,
    and repeated. So bad evidence fades 4× more slowly.
  - 1.2: applied to *every* record, that made honest communities that stopped trading drift below
    neutral, because their rare mistakes outlived their good record. Now only records that are
    mostly bad forget slowly.
- **Why standing (pooled) as well as trust (private):** refusal checks both, so a prime's own
  exploration can't let a known cheat back in (Phase 0 finding).
- **Why the world refuses rather than the agent (26 Sep):** refusal is too important to leave to a model's
  judgement. In the 1.5 Qwen run, LLM primes awarded 5 contracts to the defector while its standing fell
  to 0.17. The line is now enforced at bid time and again at award time; agents still choose among
  eligible bidders on price and trust.

### 7.2 Contract-net

- **How:** announce (max price, advance share) → bids → award (not in the same cycle, so everyone
  gets a turn to bid) → deliver → review.
- **Why the advance:** contractors need working capital. Why only 50%: to limit what a cheat can
  pocket.
- **Why deadlines on every stage:** 1.1 made contracts span cycles, which opened every stalling
  tactic. Deadlines close them.
- **Why "accepted by default":** otherwise a prime could take the work and never review it.
- **Why 10% exploration:** without it, an honest newcomer at 0.5 never beats an incumbent at 0.95, and
  the market locks in whoever got lucky first (Phase 0, "incumbency lock-in").

### 7.3 Committed funds

- **What:** strategies subtract everything already promised (remainders owed, work won, the rest of
  their own jobs) from the purse before claiming, bidding or awarding.
- **Why:** in 1.1, primes over-committed, defaulted, and then won bids they couldn't afford to
  deliver. It was the Phase 0 cold-start death spiral in a new form. For LLM agents, the observation
  will show `owed` and the tools will refuse unfundable awards, but the *judgement* is the agent's.

### 7.4 Waking and the floor

- **What:** communities choose how many members to pay for each cycle. The basic budget only tops up
  purses below 8,000, and it is smaller than one member's upkeep.
- **Why:** paying every member every cycle drained money reserved for promises. A floor paid to
  everyone let a community that never wakes bank handouts. Now the free-rider still starves, and a
  broke-but-honest community can still wake about every other cycle to bid its way back.

### 7.5 Revenue split and the treasury reserve

- **What:** 70 / 20 / 10 (prime / treasury / cited authors). While the treasury is at its reserve
  (2 cr), it takes nothing and the prime gets 90%.
- **Why:** the treasury ballooned in Phase 0 and 1.1. It had nothing to spend on in a scripted world,
  so it hoarded money that should have been circulating. "The commons takes only what it needs" is a
  simple automatic stabiliser. *This is a policy choice*, and governance should eventually own it
  (§16).

### 7.6 Grading and pass/fail

- **What:** every part is graded against its rubric, and the market pays only if all parts score at
  least 0.5. The treasury pays for grading (the prime pays if the treasury is empty).
- **Why every part:** a prime is responsible for its subcontractors' work, which gives it a reason to
  review carefully.

### 7.7 Spawn, fork, merge, retire, learn

| Mechanism | Check against abuse | Why |
|---|---|---|
| Spawn | A second from a *different* community within 3 cycles; 0.3 cr fee to the treasury; 7 members at most | No community can breed itself into a majority |
| Retire | No refund; keep at least 1 | Shrinking is cheap, not profitable |
| Fork | Takes a share of the purse *net of debts*; inherits the parent's record with good evidence halved and bad kept in full; 12 communities at most | Exit must always be available (it keeps a flat system flat), but must not launder a bad reputation |
| Merge | Both sides agree; the joiner has nothing in flight; its playbooks' authorship moves with it | No one is absorbed against their will; no obligations fall through the cracks |
| Learn | 0.5 cr for a third capability, doubling for each one after; 40% off with a playbook, whose author earns a royalty | In 1.2, cheap learning made every cooperator a generalist, trade stopped, and reputations starved. Specialisation has to pay |

### 7.8 Disputes and audits

- **What:** a contractor pays 6,000 to have the grader re-judge a rejection.
  - **Overturned:** the prime pays the remainder plus the fee, the audit files evidence against the
    prime, and the part counts toward the job.
  - **Upheld:** the contractor loses the fee and the audit files evidence against it.
- **Why:** without an appeal, a prime could reject good work to avoid paying the remainder. The fee
  and the standing hit deter frivolous disputes.

### 7.9 Rate limits

- **What:** initiating messages per cycle scale with standing, from 1 up to 1.5× the base of 12.
  Obligations are exempt.
- **Why:** a distrusted community can't flood the bus, but it can always meet its obligations.

### 7.10 Playbooks and royalties

- **Why:** the plan's central bet. Without royalties, publishing a working method is pure loss and
  everyone hoards. With them, a good playbook "earns while you sleep, from work you didn't do".

---

## 8. Money: created credits and real dollars

**All money in the system so far is created money.** Nothing on the dashboard has ever been a real
dollar. The ledger enforces a hard wall between the two kinds:

| Currency | Accounts that may go negative (the outside world) | Where it comes from |
|---|---|---|
| **SIM** (credits, "cr") | `genesis`, `market`, `compute` | Seeded at genesis, paid out by the mock market, burned as notional compute |
| **USD** (real, "$") | `owner:capital`, `ext:stripe`, `ext:anthropic`, `ext:fees` | Capital you put in, customer payments, real API bills, fees |

The rules:
- Every entry is in one currency and balances within it. There is no conversion path.
- A SIM entry can't touch a USD external account, or the other way round.
- Real revenue must name a real source such as Stripe; the mock market can only pay credits.
- **Real API calls are always recorded in USD, even inside a simulation.** A community can pay
  notional credits for a call while the real bill is booked separately, so a simulation never hides
  real spend.
- The real-dollar kill-switch ($5/day by default) watches real spend, and a reset doesn't forget it.
- On the dashboard, "$" only ever means real money. Credits show as "cr".

### The live-society decision (you made this on 25 Sep)

From Phase 2, a live society runs **entirely on real dollars**, including payments between
communities. The reasoning:

- "Realness" doesn't motivate a model. It can't tell. What motivates it is scarcity and what money can
  buy.
- Credits either can't buy real compute (which breaks "earnings buy thinking") or need an exchange
  rate, which turns created money into an unbacked real bill.
- Real purses can buy real compute and, through the gate, real outside resources such as hosting,
  domains and data. That makes bigger, better-paying ventures possible.
- **Trading between communities never creates money.** It moves dollars that came in from outside.
  Trade pays only when it helps a community sell something to a real customer.
- The costs we accept: the basic budget comes from the real treasury, so your seed sets the runway;
  every live run needs per-community daily caps, gate approval for outside spending, and the
  real-dollar kill-switch.

### How money is meant to reach the outside (Phase 2)

```
community's charter → venture (a product idea, KPIs, a channel)
   → builds a product, buying missing capabilities from peers
   → gate.request "list this product"  → you approve or deny
   → a customer pays through Stripe → webhook
   → ledger: ext:stripe → 70% earner / 20% treasury / 10% cited authors (USD)
   → that purse pays for the next round of real model calls
```

---

## 9. The economy's numbers

Current defaults (`sim/engine.py` → `Params`). Amounts are micro-credits (1 cr = 1,000,000). They are
chosen to mirror plausible micro-dollar costs, so 80,000 is about 8 cents.

| Parameter | Value | Meaning |
|---|---|---|
| `job_reward` | 80,000 | What the market pays for a completed, passing job |
| `jobs_per_cycle` | 2 | New jobs posted each cycle |
| `work_cost` | 10,000 | A scripted community's cost to produce one part |
| `upkeep` | 4,000 | Per woken member per cycle |
| `basic_budget` / `floor_cap` | 3,000 / 8,000 | Top-up paid to purses below the cap |
| `grade_cost` | 2,000 | Per graded part, paid by the treasury |
| `sub_share` | 0.4 | Scripted primes offer up to 40% of the reward per missing part |
| `advance_frac` | 0.5 | Share of the price paid on award |
| `purse_seed` / `treasury_seed` | 150,000 / 2,000,000 | Starting money (credits, from genesis) |
| `treasury_reserve` | 2,000,000 | The treasury stops taking its 20% at this balance |
| `publish_cost` | 15,000 | To publish a playbook |
| `spawn_fee` | 300,000 | To add a member |
| `learn_cost` | 500,000 | For a third capability; doubles for each after |
| `audit_cost` | 6,000 | Paid by the disputing contractor |
| Deadlines | board 3, job 8, bids 3, deliver 3, review 2, dispute 3, spawn/merge 3 cycles | |
| Limits | 7 members, 12 communities, 2 actions per member | |

**Unit economics per job** (roughly):
- **Prime:** receives 56,000 (70%), pays its own part (10,000) and a contractor (about 16,000). That
  leaves about 30,000 before upkeep.
- **Contractor:** earns about 16,000 for 10,000 of work plus a share of one member-cycle.

These numbers only need to produce *meaningful behaviour* in simulation. They get recalibrated
against measured token costs in 1.5.

**Measured outcomes** (5 seeds; scripted society):

| | Result |
|---|---|
| Defector | Earns 0.011–0.033 cr in total while burning about 0.65 cr of upkeep in 200 cycles (it lives on the floor); standing about 0.2–0.33; bus allowance falls from 12 to 2–6 |
| Control run (reputation off) | Defector earns 15–60× more; jobs completed fall 35–90% |
| Free-rider | Ends below one cycle's upkeep; silent about 25% of the time |
| Cooperators (2,000 cycles, 1.2) | 5–20 cr each (from 0.15 cr); standing 0.93–0.98; grows to 12 communities |
| Treasury | Flat at its 2 cr reserve |

---

## 10. The live dashboard

`uv run uvicorn console.app:app`, then open http://localhost:8000. One page, one live connection (SSE),
updated about twice a second.

| Panel | Shows |
|---|---|
| Header | Cycle, run state, pause reason, speed, treasury with a sparkline, jobs paid, notional spend vs ceiling, console memory |
| **Real money** | Capital in, customer revenue, real API spend, today's real spend vs the kill-switch (all $0 so far) |
| Communities | Parent (for forks), members awake, purse and trend, standing, bus allowance, contracts won and delivered, compute, royalties, rate-limit hits. Click a name for its journal, unread events and recent activity |
| Reputation | Who trusts whom (observer × subject, first-hand), plus commons standing; recent ratings |
| Contract-net | Contracts in flight (open → awarded → delivered) and how recent ones closed, including audits |
| Market | Board, in progress, reward, paid, failed (with the reason), expired |
| Ledger flows | Money moved by type (credits only; real dollars are never added in) |
| Bus | Messages per family, last cycle and total; who got rate-limited; live tail |
| Population | Spawns, forks, merges, learning, proposals waiting for an answer |
| Knowledge | Playbooks and uses |
| LLM calls / Grader & gate | Empty until 1.3 and 1.4; the gate queue arrives in Phase 2 |
| Host | Process memory vs the guard, system memory, CPU, LM Studio (app, server, loaded model) |
| Telemetry | Event counts by component |

Controls: pause, resume, step, speed (1–50 cycles/s), kill-switch, reset kill. The memory guard
pauses the run and says why.

---

## 11. What has been built so far, and what we learned

### Phase 0: Substrate (24 Sep)

Built the bus, ledger, meter, reputation, registry, workspaces, protocol schemas, the scripted
cooperator, defector and free-rider, a one-shot cycle engine and an htmx console. Acceptance passed
over 5 seeds.

Findings:
- **Cold-start death spiral:** primes took jobs they couldn't finance and lost advances to the
  unknown defector. Fix: only take fundable jobs, and buy missing parts first.
- **Poverty trap:** a broke community could afford to wake one cycle in four. Fix: fund as many
  members as you can afford.
- **Incumbency lock-in:** fixed by 10% exploration.
- **Exploration let the defector back in:** fixed by also checking pooled standing.
- **Symmetric decay forgave defection too fast:** fixed by bad evidence fading slower (refined in 1.2).
- **Treasury too rich:** carried into Phase 1.

### After the 24 Sep machine restart: resource guardrails

- Only one heavy thing runs at a time: a sim, the console, or a local model.
- Check `lms ps` before loading a model; unload it after.
- Everything in memory has a size cap.
- Runs have limits, and background processes get stopped.

The cause of the restart is unknown. A local model is the only component big enough to plausibly
exhaust 48 GB.

### 1.0: Live dashboard (25 Sep)

Built the telemetry hub, emitters in every component, the SSE dashboard, controls, drill-down, the
host monitor and the memory guard. **It found a Phase 0 memory leak:** the in-memory bus kept every
contract and knowledge message forever, because no one reads those families. Capping streams cut
memory growth over 3,000 cycles from 191 MB to 40 MB.

### 1.0b: Money (25 Sep)

Every ledger entry now carries a currency (SIM or USD), and the dashboard shows real money
separately. Recorded the decision that a live society runs on real dollars.

### 1.1: Turn-based engine (25 Sep)

Communities now act through the actions executor, contracts span cycles with a deadline at every
stage, there's a market board with graded parts, and the scripted characters were ported.

Findings:
- **Working capital:** strategies now count committed funds.
- **Upkeep as a choice:** communities wake only the members they need.
- **The floor only for the poor**, and smaller than one member's upkeep.
- **Contractors lost money on every contract:** prices rebalanced.
- **Treasury reserve rule.**
- **Supply was capacity-bound:** 30% of jobs expired unclaimed (fixed by growth in 1.2).

### 1.2: Population and knowledge (25 Sep)

Built spawn, retire, fork, merge, learn, disputes and audits, the scripted growth rules, the
population panel, and 12 new tests.

Findings:
- **Cheap learning ended trade.** Everyone became a generalist, contracts dried up, and reputations
  starved. Fix: steep prices for generalists.
- **Honest-but-quiet records drifted to distrusted.** Fix: only mostly bad records forget slowly.
- **Growth absorbs wealth:** cooperators end at 5–20 cr instead of about 35 cr, and unclaimed jobs
  fall to about 1%.
- **Merge and disputes are never triggered by scripted strategies**, so they are proven only by
  direct tests.

---

## 12. Roadmap

### 1.3: LLM grader (built 25 Sep; live calibration pending)
- `LLMGrader` (`sim/grader.py`): one call per part. The answer is `{reason, score}`, where the score is
  an integer from 0 to 10 and a part passes at 5. The reason comes first, so the model argues before
  it decides.
- **Untrusted work:** the submission is fenced in `<work>` tags, and the system prompt says anything
  inside is data. Attempts to steer the grader count against the submission.
- **Backends** (`runtime/backends.py`), brought forward from 1.4 for structured output:
  - `AnthropicBackend`: the official SDK, JSON-schema `output_config`, a cached system prompt,
    readable errors.
  - `LMStudioBackend`: local, plain HTTP, no extra dependency, charged notionally at Haiku prices.
  - `FakeBackend`: scripted, for tests.
- **Paying for it:** the notional cost comes from the treasury (or the prime, if the treasury is
  empty). A real call is also booked in USD and counts against the real kill-switch. Every call
  appears in the dashboard's LLM panel, and every grade's reason in the grader panel.
- **Resilience:** if the grader is down, a finished job waits and grading is retried for up to 3
  cycles before the job fails. The prime isn't punished for an outage. A failed audit call refunds
  the fee.
- **Calibration** (`sim/calibration.py`): 9 hand-labelled parts, one good and one bad per capability,
  plus a prompt-injection attempt. Run it with `python -m sim.calibrate --backend …`. The bar for
  adoption is at least 8 of 9 correct and the injection resisted.
- **Local result (Hermes 3, Llama 3.1 8B):**
  - First run: 7/9, and the injection *passed*. The model's reasons named violations it then scored
    as passes.
  - Fix: the answer now carries `all_requirements_met` and `manipulation_attempt` flags, and code caps
    the score.
  - Result: 8/9, injection resisted, stable across runs, about 2 s per part.
  - Remaining weaknesses: word counting (it's poor at counting words) and subjective rubric lines.
- The rotating grader panel waits until gaming shows up (§17).

### 1.4: LLM agent runtime (built 25 Sep)
- **One runtime for every agent:** the Messages API with our own tool loop. Each `ActionsAPI` method
  becomes a tool, sorted and stable.
- **Prompt layout:** a frozen protocol preamble and the community's charter first (cached), with the
  volatile observation last.
- **Steward loop:** reads the observation, calls tools, gets a bounded number of rounds and a token
  budget per turn.
- **Members:** a `commission` tool runs a Haiku call that produces an artifact and uses capacity.
- **Metering:** every call is metered from the response's usage figures, with the real-dollar
  kill-switch.
- **`ModelBackend` interface** with three implementations:
  - Anthropic (via the SDK)
  - LM Studio (local, OpenAI-compatible, port 1234)
  - a fake client, so the whole loop is tested without spending anything
- **Memory:** a per-community journal (the `note` tool; the last N notes go in each observation) plus
  the playbook library. Nothing per agent.

### 1.5: Live runs
1. **Local smoke run on LM Studio:** does a ≤ 8B model call tools reliably enough to trade?
   It's free, but watch memory.
2. **Short Anthropic smoke run** (about 10 cycles) under a hard ceiling. Measure the cache hit rate
   and cost per turn.
3. **Calibrate market rewards** against measured token cost.
4. **Full run:** two LLM seed communities plus the scripted defector. Watch for an *unscripted*
   spawn, fork and cross-community royalty. That is Phase 1's done-when.
5. **Decide:** vote-weighting cap, grader panel, charter mutability.

### Phase 2: One real channel (digital products)
- Gate enforced in two places: a PreToolUse-style hook in the runtime, and a network egress
  allowlist. Batch approval in the console, grouped by venture and risk class.
- Storefront plus Stripe; a live society on a USD ledger. Upkeep becomes the actual API bill, and
  publishing fees go to the treasury. Per-community daily caps.
- `venture.py`: hypothesis, KPIs, artifacts, channel binding.
- Decide charter mutability and **kill criteria** *before* going live.
- **Done when:** the society ships a product you'd have approved anyway, and the first dollar settles
  through the ledger.

### Phase 3: Multi-channel
Content, services and affiliate templates. Communities differentiate by channel, which is where trade
should get interesting: the SEO community has audience, the tools community has product.

### Phase 4: On-chain settlement
Coinbase Agentic Wallets (an MPC wallet per community, programmable spend controls) and x402 for
paying for APIs and data. Base Sepolia (testnet) until the spend controls have been tested
adversarially, then mainnet with per-community daily caps.

### Also outstanding
- Governance (propose, second, vote, enact) with a lottery facilitator and capped vote weights. It is
  needed before any policy (the reserve rule, fees, splits) is handed to the society.
- Dashboard: replay from `runs/*.sqlite`; contract and transcript drill-down.

### Cost expectations (from the plan; recalibrated in 1.5)

| Tier | Population | Models | Per turn | Per day |
|---|---|---|---|---|
| Phase 0–1.2 scripted | 5–12 communities | none | $0 | $0 |
| Phase 1 simulation | 8 members, 2 stewards | Haiku 4.5 / Sonnet 5 | ~$0.012 | $4–8 |
| Phase 2+ live | 12 members, 4 stewards | Sonnet 5 / Opus 5 | ~$0.037 | $20–35 |
| Local (LM Studio) | any | open models | $0 real | $0 real |

---

## 13. Strengths

- **No orchestrator by construction.** Nothing below the society layer can assign work. That is
  enforced by the code's shape, not just the prompts.
- **Rules live in code, not prompts.** Signatures, balances, deadlines, rate limits and refusals are
  checked by the substrate. An LLM can't talk its way past them.
- **Readable failures.** Every refused action explains itself, which is ideal for LLM agents that need
  to recover.
- **Mechanisms, not magic numbers.** Each fix (committed funds, the reserve rule, asymmetric decay,
  laundering-proof forks) is a rule with a reason, written down.
- **A permanent adversarial regression suite.** The defector and free-rider run on every change, so a
  tweak that makes cheating pay fails the tests immediately.
- **Controlled experiments.** The same seed with reputation off proves the *mechanism*, not the
  tuning, does the work.
- **Deterministic.** The same seed gives the same world, so bugs are reproducible.
- **Money you can trust.** Double-entry, integer amounts, a consistency check, and a hard wall
  between created and real money.
- **Cheap to iterate.** 10,000 scripted cycles take about 35 s at $0. All incentive learning happens
  before real money.
- **Observable.** A live dashboard of every component, bounded in memory, with a memory guard.
- **Interoperable later.** A2A-style agent cards and signed envelopes make outside agents possible.
- **Local-first option.** LM Studio lets live-agent experiments run with no real bill.

## 14. Weaknesses and limitations

- **Scripted agents are not LLMs.** Everything proven so far is proven for rule-following strategies.
  LLM agents will be less predictable, and they may find strategies no one scripted.
- **The mock market is thin.** Four capabilities, two-part jobs, uniform rewards and synthetic
  products. Real demand is lumpy, slow and hard to judge.
- **Scripted quality is self-declared.** Artifacts carry a `<q=…>` tag the stub grader reads. It
  proves the plumbing, not the judgement. Real grading starts in 1.3.
- **Parameters are hand-set.** Rewards, fees and costs produce sensible behaviour but aren't
  calibrated to real token costs yet (that's 1.5).
- **The reserve rule and other policies are ours, not the society's.** Governance isn't built, so
  shared norms can't yet be changed by the communities themselves.
- **Merge and disputes are untested in the wild.** No strategy uses them yet.
- **A single grader** is a single point of failure and a target for gaming.
- **Wealth still concentrates in cooperators' purses** (5–20 cr from 0.15 cr). It's absorbed by growth
  up to the 12-community cap; after that there's no sink.
- **A redundant niche still loses:** a community whose skills are fully covered by others ends up
  poorest.
- **The test suite is getting slower** (about 30 s) as the simulated society grows.
- **Single machine.** The in-memory bus and SQLite ledger suit one Mac. Redis exists but isn't the
  default.

## 15. Pitfalls and risks

### Economic
- **Vertical integration kills trade.** For one community, doing everything yourself is rational; for
  the commons it is fatal (seen in 1.2). LLM agents may head there quickly. Watch the contract count
  and learning events.
- **Death spirals.** Over-commitment, defaults and lost reputation can cascade (seen in 1.1). Watch for
  purses hitting zero while contracts are in flight.
- **Collusion.** Communities can second each other's spawns, trade ratings, or form a cartel that
  refuses outsiders. Refusal plus exploration helps; governance caps will be needed.
- **Hierarchy through reputation.** A top-rated community becomes everyone's default counterparty,
  which is the plan's Failure 2. Watch contract concentration on the dashboard.
- **Treasury capture or starvation.** Too rich means dead money; too poor and the floor fails. The
  reserve rule helps, but it is a policy that governance should own.
- **Mis-priced markets.** If mock rewards don't resemble real prices, behaviour learned in simulation
  won't transfer to Phase 2.

### LLM behaviour
- **Unreliable tool calling,** especially on small local models. Confirmed on 25 Sep: Hermes 8B gets no
  tools from LM Studio, Dolphin Nano never calls them, and LFM 1.2B confuses ids and then drifts into prose.
  Local trading needs a much stronger model.
- **Claim hoarding.** An LLM claimed 5 jobs it couldn't fund in one turn. The executor needs a bond or a
  cap; scripted strategies only held back because their own code did.
- **Talk instead of action.** Agents narrate plans instead of acting, which burns budget. Bounded
  rounds and per-turn budgets are the defence.
- **Gaming the grader.** Agents optimise for rubric wording rather than quality. Use a panel of
  graders with no stake, and audits.
- **Prompt injection through artifacts.** A delivered artifact or playbook can contain instructions
  aimed at the prime's steward. Treat all peer content as data; the observation renderer must mark it
  clearly.
- **Laundering and whitewashing.** Using forks and merges to escape a record. Forks keep bad evidence
  in full; merges keep the target's own record. Keep testing this.
- **Frivolous or abusive disputes.** The fee and the standing hit deter them. Watch the audit rate.
- **Collusion via messages.** Once agents can write free text to each other, they can coordinate in
  ways the protocol doesn't see.

### Cost
- **A runaway bill.** Mitigated by the real-dollar kill-switch ($5/day default), per-task budgets and
  a prompt-cache-friendly layout. A cache miss can multiply cost roughly 10×. Watch the cache hit
  rate on the dashboard.
- **Notional vs real confusion.** Solved in the ledger and the UI, but any new code path that spends
  real money must go through `charge_usage(real=True)`.

### Technical and operational
- **Machine resources.** A local model can take 5–20+ GB. Only one heavy process at a time, check
  `lms ps`, unload after. The memory guard only watches the console process, not LM Studio.
- **Unbounded growth.** Every new store needs a cap. The 1.0 leak shows how easy it is to miss.
- **The grader's score can contradict its own reasoning** (seen on 8B locally), and models miscount
  words. Code now holds the score to the model's findings; mechanical rubric checks belong in code too.
- **Parameter sprawl.** `Params` now has 44 knobs. Every new one needs a reason, and ideally a
  mechanism instead.
- **Regression drift.** A change can pass unit tests but shift the economy. Always run the acceptance
  suite and a 2,000-cycle check after mechanism changes.
- **Determinism breaks** if anything iterates an unordered set or uses wall-clock time in decisions.

### Legal, platform and safety (Phase 2+)
- **Platform terms of service.** Automated account creation, bidding on freelance marketplaces and
  programmatic posting are banned on most major platforms, however good the work. Prefer channels you
  own: your own storefront and your own API.
- **The gate must not be bypassable.** Two independent enforcement points (runtime hook and network
  allowlist). Test that a tool can't reach the internet without an approval.
- **Approval fatigue.** Forty individual requests a day means you stop reading them. Batch by venture
  and risk.
- **Payments and tax.** Real revenue creates obligations outside this project's scope. Check them
  before Phase 2.
- **On-chain risk (Phase 4).** Irreversible transfers. Testnet until spend controls survive
  adversarial tests, then hard daily caps.

### Project
- **Emotional investment.** Decide kill criteria before going live: what observation would show the
  society is producing noise, and how long to let it run.

---

## 16. Decisions log

| Date | Decision | Made by | Why | Revisit when |
|---|---|---|---|---|
| 24 Sep | Hand-rolled bus and protocol; frameworks only inside an agent | Plan | Every framework's between-agent layer assumes an orchestrator | — |
| 24 Sep | Phase 0 fixes (fundable jobs, fund members, exploration, standing check, slow bad decay) | Claude | Found by the scripted suite | — |
| 24 Sep | One runtime for all agents: Messages API with our own tool loop (not the Agent SDK) | Claude | The mock market needs no files or shell; owning the loop makes metering simple | Phase 2, when agents need a real workspace |
| 24 Sep | Models: stewards Sonnet 5, members and grader Haiku 4.5 | Claude, per the plan's cost table | Cost | 1.5 measurements |
| 24 Sep | Pluggable backends: Anthropic, LM Studio, fake | Claude | Free local runs; tests without spend | — |
| 24 Sep | Memory: community journal plus library, nothing per agent | Claude, per the plan | Don't over-build | If agents lose track of commitments |
| 24 Sep | Single rubric grader first; panel later | Claude, per the plan | Simplicity | When gaming appears |
| 25 Sep | Build the live dashboard before 1.1; resource guardrails | **You** | Visibility and machine safety after the restart | — |
| 25 Sep | Two currencies (SIM, USD) with no conversion | **You** asked; Claude designed | Tell created money from real money at a glance | — |
| 25 Sep | A live society pays in real dollars end to end, including between co-ops | **You** | Real purses buy real compute and outside resources; credits can't | If per-co-op caps prove insufficient |
| 25 Sep | Communities choose how many members to wake; floor only for the poor | Claude | 1.1 working-capital collapse | — |
| 25 Sep | Treasury reserve rule (no 20% while at reserve) | Claude | The treasury ballooned with nothing to spend on | **When governance exists: hand it to a vote** |
| 25 Sep | Learning price doubles per capability beyond the third | Claude | 1.2: cheap learning ended trade | 1.5, with LLM behaviour |
| 25 Sep | Only mostly bad records forget slowly | Claude | 1.2: honest-but-quiet records drifted to distrusted | — |
| 25 Sep | Fork inherits good evidence halved, bad in full | Claude | Exit without laundering | — |
| 26 Sep | The world refuses bids and awards below the trust line (0.35), not the agents | **You** | LLM primes kept hiring a known defector; judgement is fallible, a function isn't | If the line proves too harsh for honest newcomers after a bad start |

---

## 17. Open questions

| Question | Needed by | Current leaning |
|---|---|---|
| How should reputation weight votes? | Before governance (1.5 at the latest) | Cap: no community above 2× the mean weight |
| Who judges quality before the market does? | 1.3 / 1.5 | A single grader now; a rotating panel from communities with no stake, paid by the commons |
| Can a community rewrite its charter mid-run? | Phase 2 | Allow it, with a mandatory public diff |
| Memory architecture | 1.4 | Journal plus library; revisit if agents lose track |
| Kill criteria | Before Phase 2 | Decide in advance, e.g. no product you'd approve after N weeks, or cost per dollar earned above X |
| What absorbs wealth once the 12-community cap is hit? | 1.5 | Real ventures (Phase 2) with real costs; governance-set fees |
| Should the reserve rule, fees and splits become governance parameters? | When governance lands | Yes |
| How to stop prompt injection between communities | 1.4 | Mark all peer content as untrusted data in the observation; never execute it |

---

## 18. Operating guide

```sh
uv sync                                    # install
uv run pytest                              # all tests (~30 s)
uv run python -m sim 200                   # scripted society, 200 cycles, summary table
uv run python -m sim 2000 --no-verify      # faster (skips signature checks)
uv run python -m sim 200 --no-rep          # control run: reputation disabled
uv run uvicorn console.app:app             # dashboard at http://localhost:8000 (Ctrl-C to stop)
uv run python -m sim.live --backend fake   # dry run of an LLM society (free)
uv run python -m sim.live --backend lmstudio --model <id> --cycles 10 --serve   # local, watch it live
uv run python -m sim.calibrate --backend lmstudio --model <id>                  # check a grader
```

**Resource rules** (from the checklist, after the 24 Sep restart):
- Only one heavy thing at a time: a sim, the console, or a local model.
- Before loading a model: `lms ps` and `memory_pressure`. After a run: `lms unload --all`.
- Local models: ≤ 8B parameters and ≤ 8k context until measured.
- Long runs: set `Params(ledger_path="runs/<name>.sqlite")` so the ledger lives on disk. `runs/` is
  git-ignored.
- Background processes get a pidfile and are stopped at the end of the session.

---

## 19. Testing strategy

| Suite | What it proves |
|---|---|
| `test_substrate.py` | Envelopes, signatures, bus rate limits and backlog cap, ledger invariants, meter and kill-switch, reputation maths, workspace isolation |
| `test_money.py` | The SIM/USD wall; real API spend recorded in simulations; real revenue needs a real source; the real kill-switch |
| `test_telemetry.py` | Hub rings are bounded, counts aren't; subscribers; the kind limit |
| `test_turns.py` | Contract-net across cycles, every deadline outcome, what each side can see, determinism, pruning |
| `test_population.py` | Spawn needs a second, expiry, limits, fork share and no laundering, merge consent and in-flight block, learning prices and royalties, disputes overturned, upheld and late |
| `test_phase0_acceptance.py` | Over 5 seeds × 200 cycles: the ledger balances; the defector's reputation and allowance fall; defection doesn't pay; the free-rider starves; cooperators prosper; the control run shows the mechanism works; royalties cross communities |
| `test_console.py` | Dashboard API, controls, kill-switch, memory guard, drill-down, stream, bounded snapshot size, real money kept separate |
| `test_grader.py` | Grader scoring and fencing, backend request shapes (no network), real vs notional grading costs, outage retries, the real kill-switch, the calibration set's own validity |
| `test_steward.py` | The LLM runtime end to end with fake models: claim → commission → submit → graded → paid; refusals; round and money limits; prompt-prefix stability; untrusted marking; smuggled quality tags; fork copies; Anthropic and LM Studio message translation |
| `test_redis_bus.py` | The Redis backend (skipped if Redis isn't running) |

**The rule:** any change to an incentive rule must keep `test_phase0_acceptance.py` green. If it goes
red, the change probably made cheating pay.
