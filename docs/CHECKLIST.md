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
- [ ] Agent runtime (Agent SDK for stewards, Messages API tool runner for members)
- [ ] Frozen protocol preamble (prompt-cache friendly); meter wired to real usage
- [ ] Two seed communities, synthetic market + rubric grader
- [ ] Decide: vote weighting cap, grader panel, memory architecture
- [ ] Done when: unscripted spawn, fork, and a cross-community royalty

## Phase 2 — One real channel (digital products)
- [ ] Gate enforced via PreToolUse hook + egress allowlist; batch approval in console
- [ ] Storefront + Stripe connector
- [ ] Decide: charter mutability, kill criteria
- [ ] Done when: first dollar settles through the ledger

## Phase 3 — Multi-channel
- [ ] Content, services, affiliate venture templates

## Phase 4 — On-chain settlement
- [ ] Agentic Wallets on Base Sepolia, x402; adversarial spend-control tests; mainnet with caps
