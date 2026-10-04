# K6 stage 1: the trading pack, on paper

Co-ops trade paper accounts against live prices (crypto spot and US ETFs and stocks), judged by a deterministic,
risk-adjusted score settled after a horizon, and paid in credits for it (a capital economy). Stage 1 is paper only:
no account, no real money. The forward test runs for weeks on a schedule: each run loads the saved society, plays a
cycle, saves it and stops, so the laptop is busy for minutes at a time (your decisions, 3 Oct: both markets; a saved
society on a schedule).

Done when (FRAMEWORK.md §9): 30+ forward cycles on paper, with performance settled per horizon. Stages 2 (shadow) and
3 (micro-live) are separate decisions after stage 1's graduation criteria are met.

Rules for every stage: test first; commit after each item with the full suite and the golden master green; push
after each stage. The golden master moves only where a stage says so.

## Design

**Kernel (no trading words; the kernel test keeps them out):**
- **Save and resume.** A society saves its state to a file and resumes from it, with an on-disk ledger. What can't be
  saved (the lock, model backends, the web, open files) is reattached from the run's settings. Proof: a scripted run
  of N cycles equals N/2 cycles, a save, a resume and N/2 more, stream for stream.
- **Pack desks.** A pack may add a desk: its own tools (run through the command pipeline, so the lock, the activity
  log and your operator limits apply), a section of every co-op's observation, a phase in the cycle, and state that is
  saved with the society. Trading's broker is a desk; the kernel knows only "a desk".
- **Ticks.** `commons tick NAME`: resume a saved society, play N cycles, save, exit. A script around it checks memory,
  loads the model, ticks and unloads; a launchd schedule runs the script.

**The trading pack (`packs/trading/`):**
- **Prices**: a port with three adapters. A fake market (seeded random walk) for tests and the golden master;
  Coinbase spot (crypto, public API, no key); Yahoo's chart API (US ETFs and stocks, no key, unofficial; Stooq, the first choice, put its quotes behind a browser check on 3 Oct). Both live adapters go
  through the kernel's safe fetcher and its allowlist. A quote older than its market allows (the US market is shut)
  can't be traded on, and stops aren't triggered on it.
- **Broker** (pure rules, the domain): a paper account per co-op (cash, positions), market orders filled at the quote
  with modelled fees and slippage. **Limits in code from day one:** a stop-loss with every buy (between 1% and 15%
  below the entry); at most 20% of capital in one position; no shorting, no leverage, no margin; a daily loss limit
  (3% of capital: positions close and trading pauses until the next day); a kill criterion (down 20% of allocated
  capital: positions close and that co-op stops trading).
- **Performance**: per horizon (H cycles), each co-op's return net of costs, against a benchmark (equal-weight buy and
  hold of its universe over the same window), with maximum drawdown and Sortino ratio. Deterministic.
- **Capital economy**: each co-op gets notional paper capital; at each horizon, risk-adjusted excess return over the
  benchmark is converted to credits that pay for its thinking. A strategy that loses earns nothing and goes quiet.
- **Tools**: quotes and portfolio (free); buy (with a stop), sell, move a stop. Forward only: no historical data
  tool, so no backtests (models have read history).
- **Co-ops**: scripted (for tests: a holder, a momentum desk, a reckless one that tries every forbidden order) and
  LLM ones with doctrines (a crypto momentum desk, an ETF mean-reversion desk, a cautious allocator).
- **Scorecard**: excess return, maximum drawdown, Sortino, fees as a share of capital, limit breaches (floor 0).

Not in stage 1: co-ops trading research notes or risk reviews with each other by contract (the contract-net needs a
job part today); news search; shorting or derivatives; anything with real money.

## Stages

### T0. Plan (S)
- [x] T0.1 This plan
- [x] T0.2 The kernel-words test scans the real kernel (`commons/`, `sim/`); it had checked folders that no longer
      exist since R3

### T1. Save and resume (M) — kernel
- [x] T1.1 Infrastructure that can't be pickled says so: the ledger reconnects to its file, the hub drops its
      subscribers, the lock is rebuilt; model backends, the web and graders are detached and reattached
- [x] T1.2 `Society.save(path)` and `Society.resume(path, ...)`; a saved society needs an on-disk ledger
- [x] T1.3 Proof: N cycles straight equals N/2, save, resume, N/2, for both packs, stream for stream
- [x] T1.4 LLM co-ops resume with their drafts, journal and plans; their backends come from the run's settings

### T2. Pack desks (M) — kernel
- [x] T2.1 `Pack.desk`: tools, an observation section, a cycle phase, saved state
- [x] T2.2 Desk tools run through the command pipeline (lock, log, operator limits) and appear in the steward's
      tool list only for that pack (the list stays byte-stable for caching)
- [x] T2.3 A toy pack's desk runs on the unchanged kernel (acceptance test); golden unchanged

### T3. Broker (M) — pack, domain
- [x] T3.1 Accounts, positions, market orders, fees and slippage
- [x] T3.2 Limits: stop with every buy, position cap, no shorting or leverage, daily loss pause, kill criterion
- [x] T3.3 Stops triggered on fresh quotes; stale quotes refuse orders

### T4. Prices (M) — pack, adapters
- [x] T4.1 The price port and the fake market (seeded, deterministic)
- [x] T4.2 Coinbase spot and Yahoo (was Stooq) adapters through the safe fetcher; quote ages and US market hours
- [x] T4.3 Smoke test against the real APIs (by hand, 3 Oct: all eight symbols quoted; US stale on a Saturday, as it should be)

### T5. Performance and the capital economy (M) — pack
- [x] T5.1 Returns, benchmark, maximum drawdown, Sortino per horizon
- [x] T5.2 Settlement: credits for risk-adjusted excess return, paid at each horizon
- [x] T5.3 Incentives hold: on the fake market, the reckless co-op is blocked by rule and a losing one goes quiet

### T6. The trading pack (M)
- [x] T6.1 Brief, capabilities, tools, doctrines, scripted and live populations, scorecard
- [x] T6.2 Golden runs for the trading pack (scripted and fake-model)
- [x] T6.3 A dry run with fake models end to end, ticks included

### T7. Ticks and the schedule (S)
- [x] T7.1 `commons tick NAME --cycles N`
- [x] T7.2 `scripts/tick.sh`: skip if memory is short or a live run holds the lock; load, tick, unload
- [x] T7.3 A launchd plist, off until you turn it on; COMMANDS.md

### T8. The forward test (L, mostly waiting)
- [x] T8.1 First live ticks with Qwen, watched (4 Oct, `runs/ticks/paper/`): two ticks through `scripts/tick.sh`
      (cycles 1-2, then 3 resumed from the save), about 3.5 minutes each with the model loaded. Real prices
      (crypto; US closed on a Sunday); all three model-backed desks bought with stops; the 20% cap refused
      oversized orders. Found and fixed: desks paid for playbooks and a venture and searched a missing archive
      (now `Pack.without`), and a cap refusal didn't say how much would fit
- [ ] T8.2 Schedule on (your go-ahead); 30+ cycles with performance settled per horizon
- [ ] T8.3 Findings in CHECKLIST.md; graduation criteria for stage 2 written down before anyone looks at results
