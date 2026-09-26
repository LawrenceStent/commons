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
- [ ] Redesign (ideas in `docs/DASHBOARD.md`, 26 Sep): cyberpunk theme with a plain toggle, then the thought
      trace, efficiency quadrant, money flow, society network, and the rest. Not urgent
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
- [x] Each cycle, each active community takes one turn: `strategy.turn(observation, actions)`, in random order
- [x] Contract-net spans cycles: announce → bid → award → deliver → review; expiry on every stage
      (open → expired; awarded → failed, with the prime's complaint filed; delivered → accepted by
      default, or defaulted with the contractor's complaint if the prime can't pay)
- [x] Market board: jobs posted with parts per capability; claim, do parts, auto-submit; graded per part
- [x] Actions executor: validates, enforces capacity and funds, returns outcomes the agent can read
- [x] Port cooperator / defector / free-rider to turn policies; Phase 0 acceptance passes on the new engine
      (5 seeds), plus `tests/test_turns.py` for deadlines, visibility, determinism and pruning
- [x] Retune the mock market so the treasury doesn't balloon: the reserve rule below keeps it flat at 2 cr (2,000,000 micro-credits)
      over 10k cycles. 10k cycles take 35 s with signature checks and grow RSS about 59 MB

#### 1.1 findings
Moving from one-shot contracts to contracts that span cycles broke the economy first. Each fix is a mechanism:
- **Working capital.** Once work spans cycles, a community has to fund promises it made earlier.
  Primes over-committed and defaulted, and broke contractors won bids they couldn't afford to deliver. Fix:
  strategies count committed funds (`free()` = purse − remainders owed − work won − rest of own jobs)
  before claiming, bidding or awarding.
- **Upkeep is now a choice.** Paying every member every cycle drained money reserved for promises.
  Each community now `wake()`s as many members as its work needs, the way an LLM steward will decide
  how many members to commission.
- **The basic budget only tops up poor purses** (below `floor_cap`, and it is less than one member's
  upkeep). A community that never wakes can't bank handouts, and the free-rider still starves.
- **Contractors lost money on every contract** at Phase 0 prices (work 25k vs a ~40k price over two
  cycles of upkeep). Rebalanced: upkeep 4k, work 10k, reward 80k, 2 jobs/cycle, grading 2k/part.
- **Treasury reserve rule:** the commons takes its 20% only while the treasury is below
  `treasury_reserve`; above it, the earner gets 90%. Grading is paid by the treasury, or by the prime
  when the treasury is empty.
- **Open: cooperators get very rich** (120–200 cr each after 10k cycles, from a 0.15 cr start). Wealth now builds up in
  purses instead of the treasury. 1.2's spawn, fork and learn are the natural sinks; revisit prices
  in 1.5 against measured token cost.
- **Open: supply is capacity-bound.** About 30% of posted jobs expire unclaimed, because each
  community holds at most 2 jobs. Spawning (more members) is the intended answer.
- **Still open: redundant niches.** coop-b, whose capabilities overlap the other two, ends poorest.

### 1.2 Population and knowledge mechanics
- [x] `spawn` (fee to treasury, needs a second from a different community within N cycles), `retire`;
      7 members at most
- [x] `fork`: walk out with members, a pro-rata share of the purse net of debts, a subset of capabilities,
      and the parent's record with good evidence halved and bad evidence kept in full (no laundering);
      12 communities at most
- [x] `learn`: acquire a capability at a cost that doubles per capability beyond the third; 40% off when
      learning from a playbook, whose author earns 10% of the base cost
- [x] `merge` (both sides agree; the joiner must have nothing in flight; purse, members, capabilities and
      playbook authorship move; the joiner dissolves but its history and keys remain)
- [x] Playbooks carry real text; using one cites it structurally; royalties flow on revenue and on learning
- [x] Dispute → paid audit by the grader; a false rejection costs the prime (remainder + audit fee, and the
      audit files evidence against it); a fair one costs the disputer the fee and standing
- [x] Scripted cooperators second trusted peers' spawns, spawn when there's more work than members, fork
      when full, learn only to escape a crowded niche, and dispute only rejections of work that passed.
      `tests/test_population.py` covers every rule, including merge and disputes, which the scripted
      characters never trigger

#### 1.2 findings
- **Cheap learning ended trade.** Rich cooperators learned every capability, stopped needing each
  other, and contracts dried up. Fixes: generalism gets expensive (the doubling price), and the scripted
  cooperator only pivots out of a crowded niche. **Watch for this with LLM agents:** vertical
  integration is rational for one community and fatal for the commons.
- **Without trade, honest records drifted to distrusted.** Phase 0 made bad evidence fade 4× slower.
  With no fresh evidence, an honest community's rare mistakes outlived its good record. Now only records
  that are mostly bad forget slowly; a mostly good record fades evenly and keeps its ratio. The defector
  still stays refused.
- **Growth absorbs wealth.** With spawn and fork, cooperators end 2,000 cycles at 5–20 cr instead of
  about 35 cr, the society grows to its 12-community limit, and unclaimed jobs fall from about 30% to about 1%.
- **Cost:** the acceptance suite now takes about 30 s (12 communities instead of 5).
- **Not yet exercised by any strategy:** merge and disputes (tested directly). Those are the first
  things to watch for when LLM agents take over.

### 1.3 Mock market and grader
- [x] Job generator: short, cheap, gradeable tasks, with one part per capability and a rubric per part
- [x] `Grader` interface and `StubGrader` for scripted runs
- [x] `LLMGrader` (`sim/grader.py`): one structured call per part, `{reason, score 0-10}`, the work fenced
      and marked untrusted; Haiku 4.5 by default
- [x] Model backends brought forward from 1.4, structured output only (`runtime/backends.py`): Anthropic (SDK;
      `output_config` JSON schema; cached system prompt), LM Studio (local HTTP, no extra dependency), fake
- [x] Grading paid properly: notional cost from the treasury (the prime if the treasury is empty); a real call is
      also booked in USD via `meter.record_real` and counts against the real kill-switch; `llm.call` telemetry
- [x] An unavailable grader delays a finished job (retried each cycle, `grade_retries` = 3) instead of
      failing it; a failed audit call refunds the disputer's fee
- [x] Calibration set (`sim/calibration.py`): 9 hand-labelled parts, one good and one bad per capability, plus
      a prompt-injection attempt; `python -m sim.calibrate --backend fake|lmstudio|anthropic`
- [x] Calibrated on LM Studio with Hermes 3 (Llama 3.1 8B, 4.6 GB, 8k context): **8/9, injection resisted**,
      stable across runs, about 1.3–2.3 s per part. First attempt was 7/9 and the injection *passed* (see findings)
- [ ] Calibrate on Anthropic Haiku 4.5 (about a cent; needs a key and your go-ahead)

#### 1.3 findings
- **A small model's score doesn't follow from its own reasoning.** Hermes 8B wrote "the tagline has more than
  six words" and scored it 5 (pass), and wrote "violates the 50–70 word requirement" about the injection and
  scored it 6. Fix: the answer now includes `all_requirements_met` and `manipulation_attempt`, and code caps the
  score (a missed requirement can't pass; manipulation scores 0). That took it from 7/9 to 8/9 and caught the
  injection. It's a mechanism, not a prompt tweak, so it holds for any model.
- **Models can't count.** It called 62-word descriptions "46 words". Rubric lines that can be checked
  mechanically (word counts, line counts, "valid Python") should be checked in code before the model sees
  the work. Candidate for 1.5.
- **Remaining miss:** it called "FixPod" unpronounceable. That's a subjective line a small model gets wrong;
  expect some noise from a local grader and keep audits available.
- **Nine cases is a tiny eval,** and the fix was tuned while looking at them. Grow the set before trusting
  any grader with real money.
- **Speed:** about 4 s of local grading per job. Fine for tens of cycles, slow for thousands; scripted runs
  keep the stub grader.
- [x] Grading cost charged to the treasury (notional 2k/part in scripted runs; the prime pays if the treasury is empty)

### 1.4 LLM agent runtime
- [x] Frozen protocol preamble + per-community charter, cached as two system blocks; 21 tools sorted and
      stable (`runtime/render.py`, `runtime/tools.py`). The preamble explains rules and costs; it never says "cooperate"
- [x] Observation renderer: volatile content last; money in integer µcr; anything written by another
      community wrapped in `<untrusted>`
- [x] Steward loop (`runtime/steward.py`): one fresh conversation per turn; tool calls → actions executor;
      refusals come back as errors the model reads; at most 8 rounds and 80k tokens a turn; the turn ends
      if the purse can't pay for the next call; transcript kept for the dashboard
- [x] Members: `commission` runs a member call that writes a draft (D1, D2, …); `do_part`/`deliver` submit
      drafts by id so artifacts never pass back through the steward; commissioning from a playbook cites it;
      at most 2 commissions per awake member per turn; quality tags stripped from model output
- [x] Every call metered from usage via `act.record_call` (purse, notional) and in USD when real; `llm.call`
      telemetry per call; the real-dollar kill-switch applies
- [x] `ModelBackend.chat`: neutral conversation format; Anthropic replays the model's own content blocks
      unchanged (thinking-safe) and groups tool results in one message; LM Studio uses OpenAI-style function calls
- [x] Fake client (`runtime/fakes.py`): `tests/test_steward.py` runs claim → commission → do_part → grade → paid
      end to end, plus refusals, round limits, empty purse, prefix stability, untrusted marking, backend
      translation
- [x] `HybridGrader` for mixed societies (tagged scripted work → stub, real text → model); scripted reviewers
      accept untagged work from bidders they already trusted (they can't read real work: a known limitation)
- [x] Console steps the world in a worker thread under a lock (slow LLM cycles don't freeze the page);
      `stop_at` cycle limit; drill-down shows the last LLM turn
- [x] `python -m sim.live --backend fake|lmstudio|anthropic [--serve]`: 2 LLM communities (studio: design+write,
      lab: research+build), a scripted cooperator and the defector; cycle, wall-clock and real-dollar limits;
      ledger in runs/

#### 1.4 notes
- **Upkeep and token costs both apply to LLM communities** for now: upkeep is the cost of keeping members
  available, and tokens are the cost of thinking. That makes LLM communities poorer than scripted peers until
  1.5 calibrates rewards against measured token cost.
- **A mid-turn view matters.** The first build looked up jobs in the start-of-turn observation, so a job
  claimed earlier in the same turn couldn't be commissioned. `act.observe()` gives the runtime a fresh view.

### 1.5 Live run (local model first: free; Anthropic later needs a key and a spend approval)
- [x] Local smoke run on LM Studio (25 Sep): **no small local model can trade.** Details below
- [ ] Try a capable local model (Qwen 3.5 35B-A3B is downloaded and tool-capable, but 22 GB: over the
      guardrail, so it needs your OK), or go to the Anthropic smoke run

#### 1.5 local smoke findings (25 Sep)
Setup: 2 LLM communities (studio, lab), a scripted cooperator and the defector, 10 cycles, Hermes 3 8B grading.
- **LM Studio silently drops tools for models it doesn't mark tool-capable.** Hermes 3 8B got no tools (41
  input tokens) and wrote plans as prose. Fixed: `LMStudioBackend` checks capabilities and raises a clear
  error. Tool-capable downloads: Dolphin X1 Trinity Nano, LFM 2.5 1.2B, Qwen 3.5 35B-A3B.
- **Dolphin Trinity Nano (3.2 GB)** receives the tools but never calls them, even for one tool and a direct
  order. As a grader it passed everything (4/9, fell for the injection).
- **LFM 2.5 1.2B (1.25 GB)** calls tools correctly in isolation, but in the game:
  - it confuses ids (bids on job ids, announces parts of jobs it doesn't own)
  - it invents arguments
  - from cycle 4 on it answers the observation in prose ("I need clarification…")
  - it never commissions work, so no LLM job was completed
- **Two runtime fixes that help any model:** the observation now ends "This is your situation, not a
  question… act now by calling tools"; a prose reply without tool calls gets one reminder. With both,
  7 of 19 turns acted (up from 4 of 20), and the lab won a contract. Still no work produced.
- **Claim hoarding.** In one turn, studio claimed 5 jobs with money for none. Nothing in the executor
  stops it; scripted strategies police themselves with `free()`. Mechanism to decide: a claim bond forfeited
  on failure, or a cap on open claims per awake member.
- **Measured cost of thinking:** about 4,200 input tokens per steward call (preamble, tools, observation;
  no local caching), about 4,500 µcr at Haiku's notional price. Several calls a turn make thinking cost
  more than upkeep. Studio spent 99k µcr on thinking and 40k on upkeep in 10 cycles against an
  80k-µcr job reward. Rewards must be recalibrated before any LLM community can break even.
- **Observability added:** every LLM turn emits `llm.turn` telemetry, and `sim.live` writes all turns to
  `runs/*.turns.jsonl`. The in-memory transcript (last 2 turns) was too short to diagnose anything.
- The runtime itself held up: every mistake came back as a readable refusal, nothing crashed, and the
  ledger balanced in every run.
- [ ] Short smoke run (~10 cycles) with a hard ceiling; check cache hit rate and cost per turn
- [ ] Calibrate market rewards against measured token cost
- [ ] Full run: two LLM seed communities + scripted defector; watch for spawn, fork, royalty
- [ ] Decide: vote-weighting cap, grader panel, charter mutability evidence

## Framework track: one kernel, many societies (planned 26 Sep; see `docs/FRAMEWORK.md`)

**Principle added:** effectiveness and efficiency, not speed. No mechanism may reward being first.

- [ ] K1 Kernel/pack split: move market, capabilities, job templates, grader choice, the preamble's market
      section, seed population and param defaults into `packs/earn-online/`; `Pack`, `WorkSource`, `Evaluator`,
      `Society`. Done when every existing test passes with pack 0 and no domain words remain in the kernel
- [ ] K2 Tempo and efficiency: proposals-then-allocation with a claim bond (fixes hoarding); value scaled by
      quality; deferred settlement with escrow; efficiency metrics (value per unit of thought) in observation
      and dashboard; pack-set deadlines
- [ ] K3 Context and founding: brief and charter/doctrine as cached system blocks; archive and `read_archive`;
      `commons found` (blueprints drafted, you approve); per-society isolation and `runs/<society>/` layout
- [ ] K4 Second pack: tech-for-good (grant economy, brief-based work, panel + human-sample evaluator, calibration)
- [ ] K5 Member tools and the gate (web search/fetch, archive), with egress allowlist and batch approval
- [ ] K6 Trading pack: paper broker, forward-only, deterministic risk-adjusted evaluator, doctrine per co-op
- [ ] K7 OSINT pack: sourcing-first evaluator, separate verify co-op, forbidden-target policy enforced in tools
- [ ] K8 Many societies: registry, CLI, dashboard picker, per-society and total spend caps, slow-cadence scheduler

Recommended order: a minimal 1.5 (one capable model trading), then K1–K3, K4, K5, Phase 2 as pack 0's
live mode, then K6, K7, K8.

## Phase 2 — One real channel (digital products)
- [ ] Gate enforced via PreToolUse hook + egress allowlist; batch approval in console
- [ ] Storefront + Stripe connector
- [ ] Decide: charter mutability, kill criteria
- [ ] Done when: first dollar settles through the ledger

## Phase 3 — Multi-channel
- [ ] Content, services, affiliate venture templates

## Phase 4 — On-chain settlement
- [ ] Agentic Wallets on Base Sepolia, x402; adversarial spend-control tests; mainnet with caps
