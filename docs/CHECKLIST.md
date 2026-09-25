# Commons — Build Checklist

Working checklist derived from `docs/plan.html`. Tick items as they land.
Phase 0 is broken down in detail; later phases stay coarse until we reach them.

## Phase 0 — Substrate (no LLM agents)

**Done when:** a scripted defector's reputation and bus access visibly degrade over
200 simulated cycles, and a free-rider starves.

**Status (24 Sep 2026): done.** `uv run pytest` passes 56 tests, including the acceptance suite
over 5 seeds. Run a society with `uv run python -m sim 200 [--no-rep] [--seed N]`, or watch one
live with `uv run uvicorn console.app:app` (open http://localhost:8000).

### 0.1 Project skeleton
- [x] `pyproject.toml` (uv, Python 3.12, pydantic, cryptography, redis, fastapi, pytest)
- [x] Package layout: `substrate/`, `protocol/`, `society/`, `sim/`, `console/`, `tests/`
- [x] `git init`, `.gitignore`

### 0.2 Protocol schemas (`protocol/`)
- [x] Signed, content-addressed `Envelope` (Ed25519, sha256 over canonical JSON)
- [x] `contract`: announce · bid · award · deliver · settle
- [x] `reputation`: gossip · attest · dispute
- [x] `governance`: propose · second · vote · enact (schemas only in Phase 0)
- [x] `population`: spawn · retire · fork · merge (schemas only in Phase 0)
- [x] `knowledge`: publish · cite · royalty
- [x] `gate`: request · approve · deny · revoke (schemas only in Phase 0)

### 0.3 Substrate (`substrate/`)
- [x] `bus.py`: `Bus` interface; `MemoryBus` for fast sims, `RedisBus` on Redis Streams
      (one stream per family, consumer group per community); signature check on publish
- [x] Bus rate limit per community, scaled by reputation
- [x] `ledger.py`: SQLite double-entry; accounts for purses, treasury, royalty pools, market, compute
- [x] Settlement split 70 / 20 / 10 (purse / treasury / royalty pools)
- [x] Basic budget paid from treasury each cycle
- [x] `meter.py`: price table, per-call debits, per-task budgets, global daily kill-switch
- [x] `reputation.py`: direct + discounted gossip, time decay, per-capability scope
- [x] `registry.py`: A2A-style agent cards, capability lookup
- [x] Workspace isolation: one directory per community

### 0.4 Society + scripted strategies (`society/`)
- [x] `Community`: charter, members, purse, capabilities, workspace; empty purse ⇒ silent
- [x] Strategy interface (what a community does each cycle)
- [x] `Cooperator`: bids honestly, delivers, attests truthfully, publishes playbooks
- [x] `Defector`: bids on everything, takes the advance, delivers junk
- [x] `FreeRider`: no work, no bids, no market jobs; lives on the basic budget

### 0.5 Simulation (`sim/`)
- [x] Mock market: posts jobs needing capabilities no single community has
- [x] Cycle engine: floor → market → contract-net → settle → gossip → decay
- [x] Deterministic seeds; 10k cycles in 26s unverified, 74s with signature checks on every message
- [x] Per-cycle metrics series (purse, reputation, rate limit, per community)

### 0.6 Acceptance
- [x] Test: defector reputation and bus allowance fall across 200 cycles
- [x] Test: free-rider earns nothing, drains below one cycle of upkeep, goes silent part-time
- [x] Test: cooperators prosper as a class (≥2 of 3; see findings)
- [x] Control run: with reputation disabled the defector earns >10× more and output falls
- [x] Strategies kept as a permanent regression suite

### 0.7 Console (`console/`)
- [x] FastAPI + htmx: ledger balances, reputation table, live bus tail, gate queue (empty)

### Phase 0 findings (carry into Phase 1)
The first design failed in instructive ways. Each fix below is now a mechanism, not a tuning knob:
- **Cold-start death spiral.** Primes took jobs they couldn't finance, lost advances to the
  unknown defector, and bankrupted the whole society on some seeds. Fix: primes only take
  jobs they can fund, and buy missing capabilities *before* doing their own part.
- **Poverty trap.** A broke community could only afford to wake one cycle in four, so it
  never recovered. Fix: communities fund as many members as they can afford
  (min 1). Each funded member gives 2 actions per cycle, so members now matter.
- **Incumbency lock-in** (a mild case of Failure 2). An honest newcomer at 0.5 trust never beats
  a 0.95 incumbent. Fix: primes award 10% of contracts at random among bidders they don't
  refuse, and margins drift with wins and losses.
- **Exploration let the defector back in.** Fix: refusal also checks the commons' pooled
  standing, not only the prime's own view.
- **Symmetric decay forgave defection too fast.** Fix: bad evidence decays 4× slower than good.
- **Control run.** Without reputation the defector earns 13–185× more and output falls
  35–99%. Output doesn't always collapse, because per-member capacity limits how many
  contracts a defector can grab.
- **Open: redundant niches starve.** On some seeds a cooperator whose capabilities are
  fully covered by two incumbents stays poor, though it is still trusted. That's a
  market outcome, not a mechanism bug. Phase 1's pivot / merge / fork is the intended answer.
- **Open: the economy is too rich.** The treasury accumulates ~$900 over 10k cycles, so
  the mock market's rewards need to come down in Phase 1 before any behaviour means much.

## Phase 1 — Live agents, mock market

**Done when:** a community spawns an agent, another forks, and at least one playbook earns
royalties from a community that didn't write it — none of it scripted.

Decisions taken up front (revisit if they bite):
- **One runtime for every agent: Messages API with our own tool loop.** The plan said Agent SDK
  for stewards, but the mock market needs no files or shell, and owning the loop is the
  simplest place to meter every call and enforce budgets. Revisit in Phase 2, when agents need
  a real workspace.
- **Models per the plan's cost table:** stewards on Sonnet 5, members on Haiku 4.5, grader on Haiku 4.5.
- **Pluggable model backends:** Anthropic (SDK), LM Studio (local, OpenAI-compatible server),
  and a fake for tests. Local runs cost nothing real, but calls are still debited from purses
  at a notional price (Haiku 4.5 list by default), so compute-as-cost keeps its bite.
- **Memory:** a per-community journal (the last N notes go in each observation), plus the commons
  playbook library. Nothing per agent.
- **Grader:** start with a single rubric grader paid from the treasury. The rotating panel waits
  until gaming shows up.

### Resource guardrails (after the 24 Sep machine restart)
The machine has 48 GB. The one thing here that can plausibly exhaust it is a local model in
LM Studio, which starts at login. Every workstream follows these rules:
- **One heavy thing at a time.** Only one of these runs at once: a sim, the console, or a
  loaded local model. Check `lms ps` and `memory_pressure` before loading a model, and
  `lms unload --all` when a run ends. Local models stay at ≤ 8B parameters and ≤ 8k context
  until we measure their headroom.
- **Bounded by construction.** Every in-memory series has a cap: ring buffers for bus, events
  and LLM calls, and a downsampled metrics history. Long runs write to SQLite files under
  `runs/`, not to `:memory:`.
- **Runs stop themselves.** Every run has a cycle limit, a wall-clock limit and a dollar ceiling,
  plus an RSS ceiling that pauses the world and says so on the dashboard.
- **No fire-and-forget.** Background processes are started with a pidfile and stopped at the
  end of the session; `make stop` (or `scripts/stop.sh`) kills anything we launched.

### 1.0 Live dashboard (built first, so every later piece reports into it)
**Done when:** one page shows, live, what every component is doing (world, market,
contract-net, ledger, reputation, bus, knowledge, meter and LLM calls, grader, gate, and the
host process), and a run can be paused from it.
- [x] `substrate/telemetry.py`: an in-process hub. Components `emit(kind, **fields)`; the hub keeps a bounded
      ring per kind plus rolling counters, and the dashboard subscribes to it. Emitting costs nothing when no one is listening.
- [x] Engine, ledger, bus, reputation and meter emit into it (no component imports the console); ~7% run-time cost
- [x] Server-Sent Events stream (one connection) instead of a separate 1 s poll per panel
- [x] Panels: run header (cycle, speed, state, spend vs ceiling) · communities · market board ·
      contract pipeline (open → awarded → delivered → reviewed, with expiries) · ledger flows
      and treasury trend · reputation matrix · bus rate per family and tail · playbook library
      and royalties · LLM calls (model, tokens, cache hit %, cost, latency, last transcript) ·
      grader scores and cost · gate queue · host (RSS, CPU, LM Studio status). LLM, grader and gate
      panels show empty states until 1.3/1.4 emit `llm.call` / `grader.grade`; the market and contract
      panels gain open/in-flight stages once the turn-based engine exists
- [x] Drill-down: click a community to see its recent events
- [ ] Drill-down: journal, contract detail and LLM transcript (needs 1.1 / 1.4)
- [x] Controls: pause / resume / step, speed, kill-switch; RSS guard (2 GB default) trips a visible pause
- [ ] Runs attach to the dashboard or replay from a `runs/<id>.sqlite` file
- [x] Test: panels render against a real world, snapshot size stays flat as a run grows
- [x] Found and fixed a Phase 0 leak: MemoryBus kept every contract/knowledge envelope forever
      (nobody consumes those families). Streams are now capped like Redis MAXLEN; 3k-cycle RSS
      growth fell 191 MB → 40 MB, or 13 MB with `Params(ledger_path="runs/….sqlite")`

### 1.0b Money: created vs real (built 25 Sep 2026)
**Decision:** a live society (Phase 2 on) runs entirely on **real dollars**, including payments between
co-ops. Purses are shares of real pooled money (your capital plus customer revenue), so earnings can
buy real compute and, through the gate, real outside resources. Credits can't do either without an
exchange rate, and any credit created from nothing would become an unbacked real bill.
Trading between co-ops never creates money: it moves dollars that came in from outside, so trade only
pays when it helps a co-op sell something to an outside customer. Simulations run on **SIM credits**
only. Costs we accept: the basic budget comes from the real treasury, so your seed sets the runway,
and every live run has per-co-op daily caps, gate approval for outside spending, and a real-dollar
kill-switch.
- [x] Ledger carries a currency on every entry: `SIM` (created) and `USD` (real); entries balance per
      currency, and each currency has its own external accounts (SIM: genesis / market / compute;
      USD: owner:capital / ext:stripe / ext:anthropic / ext:fees). No conversion path exists
- [x] Real revenue must name a real source (`ext:stripe`); the mock market can only pay credits
- [x] Meter: `charge_usage(..., real=)`. Real API calls in a simulation are also booked in USD
      (owner:capital → ext:anthropic); local models are notional only. Real-dollar daily kill-switch
      (`real_ceiling`, $5 default), which a reset doesn't forget
- [x] Dashboard: "$" only ever means real money; credits show as "cr"; a Real money box shows
      capital in, customer revenue, real API spend, and today's real spend against the kill-switch
- [ ] Phase 2: live society on a USD ledger. Upkeep becomes the actual API bill, publishing fees go to the
      treasury rather than the compute sink, and there are per-co-op daily caps

### 1.1 Turn-based engine (prerequisite for LLM agents)
- [x] Mock market board, parts and rubrics, `StubGrader` (`sim/market.py`)
- [x] Observation / Outcome / `ActionsAPI` types (`society/observation.py`)
- [x] Actions executor (`sim/actions.py`), written against the engine API it expects; not wired up yet
- [ ] Each cycle, each active community takes one turn: `policy.turn(observation, actions)`
- [ ] Contract-net spans cycles: announce → bid → award → deliver → review; expiry on every stage
- [ ] Market board: jobs posted with parts per capability; claim, do parts, submit
- [ ] Actions executor: validates, enforces capacity and funds, returns outcomes the agent can read
- [ ] Port cooperator / defector / free-rider to turn policies; Phase 0 acceptance passes on the new engine
- [ ] Retune the mock market so the treasury doesn't balloon (Phase 0 finding)

### 1.2 Population and knowledge mechanics
- [ ] `spawn` (fee to treasury, needs a second from a different community within N cycles), `retire`
- [ ] `fork`: walk out with members, a pro-rata purse share, and discounted reputation
- [ ] `learn`: acquire a capability at a cost (the pivot out of a redundant niche)
- [ ] `merge` (both sides agree)
- [ ] Playbooks carry real text; using one cites it structurally; royalties flow on revenue
- [ ] Dispute → paid audit by the grader; a false rejection costs the prime

### 1.3 Mock market and grader
- [ ] Job generator: short, cheap, gradeable tasks, with one part per capability and a rubric per part
- [ ] `Grader` interface: `StubGrader` for scripted runs, `LLMGrader` (structured output) for live runs
- [ ] Grading cost metered and charged to the treasury

### 1.4 LLM agent runtime
- [ ] Frozen protocol preamble + per-community charter, cached; tools sorted and stable
- [ ] Observation renderer (volatile content, last)
- [ ] Steward loop: tool calls → actions executor, bounded rounds, per-turn token budget
- [ ] Members: `commission` tool runs a Haiku call that produces an artifact (uses capacity)
- [ ] Every call metered from `response.usage`; kill-switch in real dollars
- [ ] `ModelBackend` interface: Anthropic, LM Studio (`lms server start`, :1234), fake
- [ ] Fake client so the whole loop is tested without spending anything

### 1.5 Live run (local model first: free; Anthropic later needs a key and a spend approval)
- [ ] Local smoke run on LM Studio: does the model call tools reliably enough to trade?
- [ ] Short smoke run (~10 cycles) with a hard ceiling; check cache hit rate and cost per turn
- [ ] Calibrate market rewards against measured token cost
- [ ] Full run: two LLM seed communities + scripted defector; watch for spawn, fork, royalty
- [ ] Decide: vote-weighting cap, grader panel, charter mutability evidence

## Phase 2 — One real channel (digital products)
- [ ] Gate enforced via PreToolUse hook + egress allowlist; batch approval in console
- [ ] Storefront + Stripe connector
- [ ] Decide: charter mutability, kill criteria
- [ ] Done when: first dollar settles through the ledger

## Phase 3 — Multi-channel
- [ ] Content, services, affiliate venture templates

## Phase 4 — On-chain settlement
- [ ] Agentic Wallets on Base Sepolia, x402; adversarial spend-control tests; mainnet with caps
