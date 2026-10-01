# Commons — Build Checklist

Working checklist derived from `docs/plan.html`. Tick items as they land.
Phase 0 is broken down in detail; later phases stay coarse until we reach them.

## Phase 0 — Substrate (no LLM agents)

**Done when:** a scripted defector's reputation and bus access visibly degrade over
200 simulated cycles, and a free-rider starves.

**Status (24 Sep 2026): done.** `uv run pytest` passes 56 tests, including the acceptance suite
over 5 seeds. Run a society with `uv run commons sim 200 [--no-rep] [--seed N]`, or watch one
live with `uv run uvicorn commons.interfaces.console.app:app` (open http://localhost:8000).

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
- [x] `commons/substrate/telemetry.py`: an in-process hub. Components `emit(kind, **fields)`; the hub keeps a bounded
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
- [x] Mock market board, parts and rubrics, `StubGrader` (`commons/domain/market.py`)
- [x] Observation / Outcome / `ActionsAPI` types (`commons/application/observation.py`)
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
- [x] `LLMGrader` (`commons/application/graders.py`): one structured call per part, `{reason, score 0-10}`, the work fenced
      and marked untrusted; Haiku 4.5 by default
- [x] Model backends brought forward from 1.4, structured output only (`commons/adapters/models.py`): Anthropic (SDK;
      `output_config` JSON schema; cached system prompt), LM Studio (local HTTP, no extra dependency), fake
- [x] Grading paid properly: notional cost from the treasury (the prime if the treasury is empty); a real call is
      also booked in USD via `meter.record_real` and counts against the real kill-switch; `llm.call` telemetry
- [x] An unavailable grader delays a finished job (retried each cycle, `grade_retries` = 3) instead of
      failing it; a failed audit call refunds the disputer's fee
- [x] Calibration set (`commons/application/calibration.py`): 9 hand-labelled parts, one good and one bad per capability, plus
      a prompt-injection attempt; `commons calibrate --backend fake|lmstudio|anthropic`
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
      stable (`commons/agents/llm/render.py`, `commons/agents/llm/tools.py`). The preamble explains rules and costs; it never says "cooperate"
- [x] Observation renderer: volatile content last; money in integer µcr; anything written by another
      community wrapped in `<untrusted>`
- [x] Steward loop (`commons/agents/llm/steward.py`): one fresh conversation per turn; tool calls → actions executor;
      refusals come back as errors the model reads; at most 8 rounds and 80k tokens a turn; the turn ends
      if the purse can't pay for the next call; transcript kept for the dashboard
- [x] Members: `commission` runs a member call that writes a draft (D1, D2, …); `do_part`/`deliver` submit
      drafts by id so artifacts never pass back through the steward; commissioning from a playbook cites it;
      at most 2 commissions per awake member per turn; quality tags stripped from model output
- [x] Every call metered from usage via `act.record_call` (purse, notional) and in USD when real; `llm.call`
      telemetry per call; the real-dollar kill-switch applies
- [x] `ModelBackend.chat`: neutral conversation format; Anthropic replays the model's own content blocks
      unchanged (thinking-safe) and groups tool results in one message; LM Studio uses OpenAI-style function calls
- [x] Fake client (`commons/agents/llm/fakes.py`): `tests/test_steward.py` runs claim → commission → do_part → grade → paid
      end to end, plus refusals, round limits, empty purse, prefix stability, untrusted marking, backend
      translation
- [x] `HybridGrader` for mixed societies (tagged scripted work → stub, real text → model); scripted reviewers
      accept untagged work from bidders they already trusted (they can't read real work: a known limitation)
- [x] Console steps the world in a worker thread under a lock (slow LLM cycles don't freeze the page);
      `stop_at` cycle limit; drill-down shows the last LLM turn
- [x] `commons run --backend fake|lmstudio|anthropic [--serve]`: 2 LLM communities (studio: design+write,
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
- [x] Qwen 3.5 35B-A3B locally (26 Sep, your OK to exceed the guardrail): **it can trade.** Details below
- [x] Fix the two problems it exposed (26 Sep):
  - **Members never reason.** Tested on Qwen: `/no_think`, `chat_template_kwargs` and `reasoning_effort: low`
    all still reason until the allowance runs out; only `reasoning_effort: "none"` works (a 60-word description
    in 2.1 s and 75 tokens, against 2,500 tokens and nothing written). Anthropic members run with thinking off.
    An all-reasoning reply now reads as "out of tokens", and the refusal says the call was still charged.
  - **A calibrated live economy** for LLM runs (`commons/interfaces/cli/live.py`): reward 400k, purse 400k, upkeep 2k, scripted
    work cost 40k, fees scaled to match, and longer deadlines (board 5, job 12, bids 4, deliver 5, review 3).
    Scripted runs keep their defaults, so the regression suite is unchanged. Steward reasoning capped at
    6,000 tokens a call.
- [x] Rerun with Qwen on the fixes (26 Sep): 10 cycles in 20 minutes; results below
- [x] Parallel turns (`Params.parallel_turns`, on for `commons run`): stewards think at once, actions apply one at a
      time under the world's lock; the dashboard updates mid-cycle. Not yet measured on a live run
- [x] `runs/live.pid` is a lock: a second live run refuses to start (a dry run had overwritten and deleted the
      real run's pid file). Member commissions are now in the activity log; every entry has a timestamp

#### 1.5 Qwen rerun results (26 Sep, after the fixes)
Qwen 3.5 35B-A3B for steward, member and grader; the calibrated live economy; sequential turns.
- **Speed:** 10 cycles in about 20 minutes (about 2 minutes a cycle, down from about 5), because members no
  longer reason and steward reasoning is capped.
- **Members work now:** 16 of 22 commissions produced drafts. The 6 refusals were stewards commissioning work for
  contracts they hadn't won yet, not members failing.
- **Protocol use:** 47 of 75 steward tool calls succeeded. announce 9/9, bid 7/7, deliver 3/3, attest 3/3,
  award 8/10, review 6/7. The misses: claim 5/20 (15 hit the two-job cap, and the stewards kept retrying),
  do_part 5/14 (re-submitting parts already done).
- **Trade between LLMs and others:** lab sold research to coop-b twice (both accepted, both jobs paid); studio
  sold writing to lab (accepted). 4 jobs were paid in all, every one with a scripted prime.
- **No LLM-prime job was paid.** Lab's J1 failed grading because studio's write part invented a statistic
  ("thousands of…"), which the grader caught (0.30). The grader did its job.
- **LLM primes kept hiring the defector:** 5 awards to it, even as its standing fell to 0.17. They rejected every
  junk delivery correctly, but paid the advances each time. **The stewards don't weigh trust when awarding.**
  Scripted primes refuse below 0.35 in code. To decide: show trust more prominently, warn on low-standing bids,
  or let the substrate refuse (that would be a rule, not a prompt).
- **The first audit by the market went against an LLM:** lab rejected good design work from coop-b; coop-b
  disputed, the audit overturned it (0.81), and lab, unable to pay the remainder, defaulted. The mechanism
  worked as designed.
- **Decision log is rich:** 29 steward statements and 65 actions with a `why` (for example, "Claim sourdough
  starter kit job - write part matches our capabilities, can outsource build"). **Goals and ideas: not used
  at all.** Qwen ignored the new tools.
- **Money:** studio spent 405,884 µcr on 58 model calls and lab 416,157 on 59 (about 7,000 per call). They
  earned 100,000 and 300,000 in contracts. Thinking still costs about 4× what they earn: studio ended broke,
  and lab with 86,803. Standing: studio 0.83, lab 0.71.
- **Decided 26 Sep: the world refuses, not the model.** `World.eligible(prime, bidder, capability)` refuses any
  bid, and any award, where the bidder's standing or the prime's own record of them in that capability is below
  `bid_floor` (0.35). It runs at bid time and again at award time, since standing can fall between the two. The
  steward sees each bid marked eligible or refused, with the reason, and still chooses freely among eligible
  bidders. Control runs (reputation off) refuse no one. Scripted check, 3 seeds × 200 cycles: the defector
  wins its first 2 contracts before there is evidence, then none; it earns 11,200 µcr vs 400,000–760,000
  without reputation.
- **Next:**
  1. ~~make trust visible where awards are decided~~ (done: the world refuses)

#### 1.5 Qwen run 3 (26 Sep): parallel turns, world rules against waste, no local token caps
Same seed (same market) as run 2, so differences come from the changes.
- **Money: both LLM communities made a profit for the first time.** Studio ended at 435,652 µcr and lab at
  452,809, from 400,000; neither ran out of money. Studio earned from contracts (it sold writing to the scripted
  co-op twice). **Lab earned 160,000 µcr in royalties** from a build playbook it wrote itself in cycle 1, cited 4
  times by the scripted co-op.
- **The first LLM-prime jobs were paid:** J4 (studio) and J6 (lab). 6 jobs paid and 1 failed in all. J5 failed
  grading on its build part (0.40).
- **Phase 1 goal, partly met:** a playbook earned royalties from a community that didn't write it, and the
  author was an LLM that decided to publish unprompted. The *citing* was scripted (the co-op cites library
  playbooks by rule), so it isn't yet "none of it scripted". Lab also tried to spawn in cycle 1 but couldn't
  afford the 1.5M fee from a 400k purse, so the live spawn fee needs recalibrating.
- **Speed:** turns took 22.3 minutes in total, against 40.8 if back to back (**1.8× faster**). Normal cycles
  take 45–90 s. Cycles 7 and 8 took about 9 and 3.5 minutes because audits ran the grader, with no token cap,
  **while holding the world's lock**, so every action waited. **Fix next: grade outside the lock.**
  *Fixed 26 Sep (b5fbae4):* jobs are queued for grading and disputes file audits; `settle_grading` runs after the
  turns, makes the model calls without the lock, and applies verdicts under it. Payment lands at cycle end.
- **Wasted calls:** 69 of 97 calls succeeded (71%, up from 63%). The world rules removed both big sources:
  refusals at the claim limit and re-submitted parts went from 24 to 0. What remains is mostly the **race that
  parallel turns created**: 13 refusals were claims on jobs another steward took first, or announcements for
  jobs it then didn't own. K2's allocation removes it; until then it costs about one round per race.
- **Decided 26 Sep (option B, built):** the grader judges every delivery; see "Reviews by the grader" below.
- **LLM reviewers are too harsh:** both LLM primes rejected good work (studio → lab's research, lab → the
  scripted co-op's design), and both were overturned on audit. Lab's standing fell to 0.43, close to the 0.35
  line. Candidate world rule: the grader, not the prime, decides contract reviews (or a rejection triggers an
  automatic audit). Needs your decision.
- **The defector** won 1 contract before there was evidence, was rejected, then was refused by the world;
  it ended at 0.33.
- Goals and ideas: still unused (0). Decisions logged with a `why`: 79. No reminders needed.  2. cut wasted calls (retrying refused claims and done parts)
  3. measure parallel turns
  4. revisit the price of thinking: calls are cheaper than before, but a steward still makes about 6 per turn
- [x] **Activity log** (`commons/substrate/activity.py`): every action through the executor (scripted and LLM), every steward
  decision (its words, and an optional `why` on any tool call) and every world change (jobs, contracts, grades,
  audits, population, playbooks, kill-switches) in one timeline. A bounded ring in memory (2,000 entries); live
  runs also stream it to `runs/<run>.activity.jsonl`. 2,000 scripted cycles log 55k entries at no measurable cost
- [x] **Ideas and goals** (`commons/domain/goals.py`): `idea`, `set_goal` (a checklist of up to 12 steps, optionally from an
  idea), `update_goal`. Active goals and recent ideas are shown back in the observation every turn: the steward's
  memory across turns, alongside the journal
- [x] **Dashboard:** "Goals & progress" (every community's goals with checklists and progress bars, plus every
  claimed job as an automatic checklist of its parts), "Ideas", and a filterable "Activity log"; the drill-down
  shows that community's actions and decisions
- [ ] Anthropic smoke run (Sonnet 5 steward, Haiku members/grader, $1 cap): needs `ANTHROPIC_API_KEY`

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
- **Observability added:** every LLM turn emits `llm.turn` telemetry, and `commons run` writes all turns to
  `runs/*.turns.jsonl`. The in-memory transcript (last 2 turns) was too short to diagnose anything.
- The runtime itself held up: every mistake came back as a readable refusal, nothing crashed, and the
  ledger balanced in every run.

#### 1.5 Qwen 3.5 35B-A3B findings (26 Sep)
Setup: Qwen as steward, member and grader; 16k context; loaded alone (20.6 GB; memory 19–21% free
throughout, back to 80% after); stopped after cycle 4 once both LLM communities were broke.
- **As a grader: 8/9, injection resisted,** with the most precise reasons so far (it counted the long tagline
  at fifteen words). But 20–45 s per part, and it needs about 6,000 tokens of room because it reasons first.
- **As a steward, it trades.** 24 tool calls, 16 succeeded: claim 4/4, announce 4/4, bid 4/4, award 2/2,
  deliver 1/1. Studio awarded lab a research contract and lab delivered it: the first LLM-to-LLM trade.
  One id mix-up (a contract id used as a job id). About 5 minutes per cycle.
- **Members that only reason.** 4 of 8 commissions returned nothing: the member spent its whole allowance
  (6,000 tokens) reasoning and never wrote the work, and the empty call was still charged. Options: turn
  reasoning off for members (they write, they don't plan), cap the reasoning budget, or don't charge a
  call that produced no content. Needs a test with the model loaded.
- **Thinking is priced too high for a reasoning model.** Charged at Haiku's output rate, calls averaged
  10,100 µcr and peaked at 30,300 µcr (a third of a job's reward). 26 calls consumed 262,000 of the two
  communities' 300,000 µcr in three cycles. This is the reward-calibration question in its sharpest form:
  either rewards rise several-fold, or local reasoning is priced lower, or reasoning is budgeted per call.
- **Operations:** `uv run` wraps the process, so a signal to the wrapper doesn't reach the world (fixed:
  `commons run` writes its own pid to `runs/live.pid`). A monitor that uses `pgrep -f` matches its own command
  line. Snapshots wait for the world's lock, so on slow runs the dashboard only updates between cycles
  (improvement: take the lock per turn rather than per cycle).
- [ ] Short smoke run (~10 cycles) with a hard ceiling; check cache hit rate and cost per turn
- [ ] Calibrate market rewards against measured token cost
- [ ] Full run: two LLM seed communities + scripted defector; watch for spawn, fork, royalty
- [ ] Decide: vote-weighting cap, grader panel, charter mutability evidence

#### 1.5 follow-ups (28 Sep)
- [x] **Grade and appraise in parallel** (`grading_workers`, 4 in `commons run`): calls run 4 at a time outside the lock;
      verdicts apply in a fixed order, so outcomes don't depend on timing
- [x] **World rule: commission only for what you can deliver.** The observation lists exactly what a co-op can commission
      for; anything else is refused with that list; a second commission for a part with an unused draft is refused
      with the draft's id

#### 1.5 Qwen run 4 (27 Sep): option B, ventures, the operator, lower spawn and learn fees
Same seed and model as runs 2–3; operator folder = a copy of `operator.example/`.
- **Money:** studio 400k → **1,211,593 µcr** (3×): 3 of its own jobs paid plus writing sold to three co-ops. Lab 400k →
  327,442: its funded venture failed grading, and it spent 40k on venture fees and 60k publishing a playbook.
- **4 LLM-prime jobs paid** (studio J1, J4, J10; lab J6), up from 2. 7 of 8 jobs paid in all.
- **Option B worked cleanly:** 8 contract deliveries graded; 6 accepted, 2 rejected, and both rejections were the defector's junk
  (0.04 and 0.06). **No false rejections, no disputes, no audits.** The grader's reasons are specific ("58 words", "exactly
  six words", "no invented statistics").
- **The first LLM ventures:** lab pitched "Buyer Needs Analyzer" in cycle 1 (score 4, rejected), revised, and pitched
  "Order Validation Tool for E-commerce" in cycle 2 (score 6 → job V3, reward 440,000 µcr). V3 then **failed grading**: the
  grader found an operator-precedence bug in the build part (0.40). The market worked as designed: a self-made job is paid only
  if the work passes.
- **Spawn:** the scripted co-op B added a member, **seconded by lab** (an LLM), now that the fee is affordable. No LLM co-op
  spawned or forked itself yet.
- **The operator:** the house-style context showed up in the decision log ("Create draft for J1 write part following house
  style"). No limit was hit (studio never neared its price cap or thinking budget).
- **Calls:** 64 of 92 succeeded (70%). Refusals are now mostly the job race (6) and commissioning for contracts not won or
  already delivered (9, studio's last turn).
- **Timing:** 33.7 minutes for 10 cycles; turns took 20.7 of them. Most of the rest is grading, which now runs outside the
  lock but **one call at a time**. Next: grade in parallel (LM Studio serves 4 at once).
- Goals and ideas: still unused.

### 1.6 Ventures: co-ops propose their own work (built 26 Sep)
Until now every paying job came from the market's seeded board, so a co-op's own reading of its charter
had nowhere to go (and the idea and goal tools went unused).
- [x] `propose_venture(title, pitch, parts, idea_id)`: 1–3 parts, each a different capability with a spec and a
      checkable rubric; a fee to the treasury
- [x] Deterministic rules refuse at once: standing below the line, a proposal already waiting, at the job limit,
      unknown or repeated capabilities, vague or oversized parts, a near-copy of existing work (word overlap ≥ 0.7)
- [x] An appraiser scores at the start of the next cycle, **outside the world's lock**: coherence, plausible demand,
      whether the rubrics can really be graded, padding, manipulation. Code holds the score to those findings
      (incoherent or manipulative → 0; ungradeable or padded → at most 4)
- [x] A fixed formula sets the reward: nothing below 5/10, then 0.5×–1.5× the base job reward
- [x] Approval by score, never by who asked first, within `venture_budget` per cycle; the rest wait their turn
- [x] An approved venture becomes the proposer's own claimed job, graded and paid like any other
- [x] Dashboard: ventures beside ideas; activity log records proposals and decisions; `commons run` uses `LLMAppraiser`
- [x] Calibrate the appraiser (28 Sep): 8 hand-labelled pitches (4 fund, 4 not: vague rubric, trivial padding, incoherent,
      manipulation). Qwen scored **6/8** at first: it rejected all bad pitches but also two good small ones, treating
      "small" as "trivial". One clarification in its instructions (small is not trivial; trivial = work anyone does in
      seconds) → **8/8, manipulation resisted** (bad pitches 0–2, good 7–9). Caveat: tuned on the same small set; grow it
      before trusting the appraiser with real money
- [x] Live run (27 Sep): lab proposed 2 ventures, one funded (score 6, 440k); it failed grading on a real bug
- [ ] Watch for: easy rubrics written to be passed (the appraiser's `gradeable` check is the defence), and
      ventures crowding out the board

### Reviews by the grader (option B, your decision, 26 Sep)
- [x] A delivery is queued and graded at the end of the cycle, outside the lock, against the part's rubric. Pass: the
      prime pays the rest automatically (or defaults if it can't). Fail: rejected; the contractor keeps the advance
- [x] The delivery's grade is stored on the job and reused when the job is graded, so no part is graded twice (tested)
- [x] The prime's record of the contractor still updates from the verdict (it did receive the work)
- [x] `review` and `dispute` are gone from the steward's tools; the actions refuse with a reason. A grader outage
      retries, then accepts by default so contractors aren't punished for it
- [x] `Params.grader_reviews` (on by default); off restores prime reviews and disputes, which stay tested
- [ ] Later: appeals against the grader itself go to a panel of graders from uninvolved co-ops

### 1.7 Operator: your directives, context and limits (built 26 Sep)
- [x] `operator/` folder (copy `operator.example/`; the real one is git-ignored): `all.md` and `coops/<name>.md`
      directives, `context/` reference files, `config.toml` for context lists, limits and runtime settings
- [x] **Directives** and **context** go into a trusted third block of the steward's system prompt, headed as coming
      from you, apart from anything peers wrote. Context is capped at 12,000 characters per co-op
- [x] **Limits are world rules**, checked before every action for scripted and LLM co-ops alike: `forbid` (action
      names or groups like `merge`, `spawn`, `venture`; unknown names are an error, never a silent allow),
      `max_price` for bids and announcements, `max_jobs`, `thinking_budget` (µcr of model calls per turn). A co-op's
      own limit can only tighten the shared one
- [x] **Runtime settings** per co-op: steward and member models, rounds, reply sizes
- [x] Re-read every cycle; a broken config keeps the last good one and shows the error; every change is in the
      activity log. The dashboard's Operator panel shows each co-op's limits and context and edits directives live
- [x] `commons run --operator DIR`; 10 tests in `tests/test_operator.py`, including path escapes and unknown limits
- [x] Large material: the searchable archive (built in K3), so big documents don't ride along on every call

## Architecture refactor (from 1 Oct; see `docs/REFACTOR-PLAN.md`)

The audit (`docs/ARCHITECTURE-AUDIT.md`) found the rules sound and the structure outgrown: a 1,000-line `World`,
package cycles, a flag-driven economy, duplication. The refactor moves the code to Ports and Adapters with DDD
tactical patterns, protected by a golden master that pins today's runs byte for byte. Progress is the per-stage
checklists in the plan (R0 to R12), on branch `refactor/architecture`; no feature work until it merges.

- [x] Done 1 Oct, R0 to R12, each stage committed with the full suite and the golden master green; behaviour
  unchanged. The layers and how to extend them: `docs/ARCHITECTURE.md`. Every command: `docs/COMMANDS.md`.
- [ ] After the merge, with your approval: the three bugs found along the way (`REFACTOR-PLAN.md` §7) and type
  checking (R13, proposed)

## Framework track: one kernel, many societies (planned 26 Sep; see `docs/FRAMEWORK.md`)

**Principle added:** effectiveness and efficiency, not speed. No mechanism may reward being first.

- [x] K1 Kernel/pack split (28 Sep). `commons/domain/pack.py`: `Pack`, `WorkSource`, a generic `TemplateWorkSource`, `load(name)`.
      `packs/earn_online/`: its skills, job templates and products, scripted and live co-ops, live economy, a brief
      (now a cached block in every steward's prompt), its own grader, appraiser and member instructions, and both
      calibration sets. The kernel's prompts are neutral defaults. `--pack NAME` on `sim`, `commons run`, `sim.calibrate`.
      **Done-when met:** all tests pass with pack 0; scripted runs on seeds 0, 3 and 7 are byte-identical to before;
      `tests/test_kernel.py` fails if a domain word enters the kernel, and runs a toy garden pack on the kernel
      unchanged. (The grader and appraiser interfaces stayed as they are; a separate `Evaluator` for delayed
      outcomes comes with K2/K6, when a pack needs one.)
- [x] K2 Tempo and efficiency (28 Sep):
  - **Allocation, not a race:** claims are registered during a cycle and allocated at its end: most trusted, then
    best fit (parts it can do itself), then least loaded; ties by a draw seeded from the job. Tested: the first to
    claim doesn't win, and swapping who asks first doesn't change the winner
  - **Claim bond:** 10% of the reward into escrow on winning; returned when paid, forfeited to the treasury if the job
    fails. **Tested: a hoarder that claims everything and works nothing loses bonds and ends poorer than a cooperator**
  - **Pay scales with quality:** half the reward depends on the mean part score (`quality_pay`); every part must pass
  - **Deferred settlement:** a grade may say `settle_after` N cycles; the job waits ("graded"), the grader may re-judge
    via `settle(job)`, then it pays or fails. Groundwork for trading and OSINT
  - **Efficiency:** earned per unit spent thinking, in every observation ("Efficiency: earned X for Y spent") and on a
    dashboard panel (earned against spent, with the break-even line)
  - **Pack-set deadlines:** already possible (deadlines are params a pack overrides)
  - **Findings:** allocation costs scripted societies about 25% of jobs (a prime starts work the turn after winning), the
    price of removing the race. Economy is leaner: cooperators 1.9–2.6 per unit of thought, defector 0.02. Without
    reputation, bonds can collapse the whole economy (primes keep hiring the defector and forfeit), so the control-run
    check now accepts either "defection pays 10×" or "output below 10%"; both show reputation doing the work
- [x] K3 Context and founding (28 Sep):
  - **Society folders:** `societies/<name>/` (git-ignored) holds `society.toml` (pack, seed), `brief.md`,
    `blueprints.toml`, `archive/`, `playbooks/`, an optional `operator/`, and its own `runs/`. `society.example/` shows one
  - **Founding:** `commons found NAME --pack P --brief FILE [--context DIR] [--coops N] --backend ...` makes one
    structured model call that drafts blueprints (name, kind, members, capabilities, charter, doctrine). Doctrines named
    in the brief are copied word for word; context is summarised into the call as untrusted reference. Founding happens
    once: a folder with blueprints is refused
  - **Approval is yours:** you edit `blueprints.toml`, then `--approve` checks it against rules (2–12 co-ops, unique
    names, 1–7 members, capabilities from the pack, LLM co-ops need a charter; warnings for all-skill co-ops and
    uncovered skills). `commons run --society NAME` refuses unapproved or rule-breaking blueprints
  - **Brief and doctrine as cached blocks:** the society's brief is added to the pack brief ("THIS SOCIETY, IN ITS
    OPERATOR'S WORDS"); a co-op's doctrine (how it works) sits beside its charter (what it's for) in its own block
  - **Archive:** `commons/application/archive.py` splits `.md`/`.txt` into ~800-character passages ranked with BM25 (no model call).
    Stewards get free `search_archive(query)` and `read_archive(passage_id)` tools; the observation says how many
    passages exist. Shown as reference, never as instructions
  - **Seed playbooks:** `playbooks/<capability>--<title>.md` go into the library at genesis, authored by "operator",
    earning no royalties
  - **Done-when met (fake backend):** founded from `society.example/brief.md`, approved, and run with
    `commons run --society`; 6 tests in `tests/test_founding.py`. A real drafting call (Qwen) is still to do
- [x] K4 Second pack: tech for good (28 Sep). `packs/tech_for_good/`: skills scout, assess, design, write; jobs from
      subjects (a society's own `questions.md` replaces the defaults); its own brief, grader, appraiser, member
      instructions, a three-lens grader panel, a scorecard, and calibration sets (8 grader cases, 7 proposals).
      What the kernel gained (general, not tech-for-good specific; the domain-word guard now covers both packs):
  - **Grant economy** (`Params.economy = "grant"`): a funder tops up a pool by `grant_budget` each cycle (at most
    `grant_cap_cycles` budgets banked); at cycle end passing work shares it by value, never more than its value.
    Stewards see the pool in their observation. The market economy is unchanged: pack 0 runs byte-identical on
    seeds 0, 3 and 7 apart from the new scorecard lines
  - **Grader panel** (`PanelGrader`, `commons run --panel`, `commons calibrate --panel`): each lens grades; the median counts
  - **Scorecard** (`commons/domain/scorecard.py`): a pack's mission metrics plus general ones (efficiency, concentration,
    cooperation, citation validity), each measured by code, grader or you, with targets and floors; breaches are
    logged. The headline panel of the dashboard and the end of every summary
  - **Your ratings** (`commons/application/ratings.py`, `commons rate NAME`): every Nth paid job is set aside in the society
    folder; your 0–3 rating feeds the scorecard and is first-hand reputation evidence (observer "operator")
  - **Made-up citations fail by rule:** work citing an archive passage as `[archive: <id>]` that doesn't exist scores
    0 before any grading; valid and invalid citations are counted
  - **Members work from sources:** `commission(..., sources=[passage ids])` puts archive passages in the member's
    prompt, to cite
  - **Done-when met:** the Phase 0 acceptance checks hold on this pack in the grant economy (seeds 0–2: defector below
    0.35 and winning nothing, free-rider starves, cooperators prosper); grants never exceed the budget; a society is
    founded from `society.tech-for-good.example/` and run with a panel (fake models); 21 tests in `tests/test_k4.py`.
    **Calibrated on Qwen 3.5 35B-A3B:** grader 8/8 (injection resisted), appraiser 7/7 (harmful personal-data proposal
    and manipulation refused), three-lens panel 8/8 (the evidence lens alone failed both good pieces at 4, over "(unverified)" details; the median carried them, which is what a panel is for). A panel costs three times as much: about a minute per call per lens on Qwen
  - **Not yet:** a live LLM run of this pack; rating from the dashboard (the CLI only for now); members still can't
    search the web (K5), so evidence is the archive or marked (unverified)
- [x] K5 Member tools and the gate (30 Sep). Nothing reaches the internet unless your policy allows it or you approved it,
      enforced in two independent places:
  - **The gate** (`commons/application/gate.py`, the tool layer): every web call is a request with a risk class (read; contact, publish
    and spend are reserved and can never be "allow"). Your `[gate]` policy in the operator's config.toml: `read = ask |
    allow | deny`, `allow_hosts`, `per_cycle` (a rule), `ttl`. "ask" queues the request; you decide on the dashboard's
    Gate panel (batched by co-op, tool and host, with "always" for a standing approval and revoke) or with
    `commons approve NAME` (decisions via `gate.jsonl` in the society folder). Approved requests run at the start
    of the next cycle and the asker is told the result. Every request and decision is logged
  - **The network layer** (`commons/adapters/web.py`), independent of the gate: https only, allowlisted hosts only (each
    redirect hop checked), no IP literals or private addresses, robots.txt respected (search APIs excepted), text only,
    size caps, GET only, a User-Agent that says what it is
  - **Web pages join the archive** (kept in `archive/web/` for later runs), so the citation rule covers them: citing a
    page nobody read fails. Search is Wikipedia's API (free, no key), behind the same allowlist
  - **Members use tools:** a commissioned member may look things up (search/read the archive, search/read the web) for
    up to `member_rounds` (4) rounds before writing; nothing else. Stewards get the web tools only when the society has
    web access (the tool list stays byte-stable for caching). `forbid = ["web"]` turns it off per co-op
  - **Done-when met:** `tests/test_k5.py` (24 tests) proves a gated read never reaches the network without approval
    (none when pending, denied or expired; approved runs next cycle), that the network layer refuses off-list hosts
    even after the gate approved, and every egress rule. Real smoke test (30 Sep): a Wikipedia search and one page
    read, each held until approved, the off-list host refused, 3 requests in all. Pack 0 still byte-identical
  - **Not yet:** a live LLM run using the web; other search providers (a key-based one, if you want the whole web);
    contact, publish and spend tools (Phase 2 builds the first, behind this gate)
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
