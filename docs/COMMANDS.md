# Commands and scripts

Every command and script used to build, run and check Commons, with every option. Run them from the repository root.
Since the refactor (R3, 1 Oct) there is one command, `commons`, with a subcommand per job:

| Command | What it does | Costs | Section |
|---|---|---|---|
| `uv run commons run` | Runs a live society (LLM co-ops) | Fake: nothing. LM Studio: your machine. Anthropic: real money | [run](#commons-run) |
| `uv run commons sim` | Runs a scripted society (no models) | Nothing | [sim](#commons-sim) |
| `uv run commons found` | Founds a society from your brief; approves its blueprints | One model call (or none with `fake`) | [found](#commons-found) |
| `uv run commons approve` | Decides what agents asked the gate for (web reads) | Nothing | [approve](#commons-approve) |
| `uv run commons rate` | Rates the work a society set aside for you | Nothing | [rate](#commons-rate) |
| `uv run commons calibrate` | Checks a grader or appraiser against hand-labelled cases | One call per case (per lens with `--panel`) | [calibrate](#commons-calibrate) |
| `uv run uvicorn commons.interfaces.console.app:app` | The dashboard on a scripted society | Nothing | [dashboard](#the-dashboard) |
| `uv run pytest` | The test suite, golden master included | Nothing | [tests](#tests) |
| `uv run python -m tests.golden.update` | Regenerates the golden-master fixtures | Nothing | [tests](#tests) |
| `uv run python -m tools.arch_metrics` | Architecture measurements | Nothing | [metrics](#architecture-metrics) |

`python -m commons …` works the same as `uv run commons …` inside the virtual environment. The old commands
(`python -m sim`, `sim.live`, `sim.found`, `sim.rate`, `sim.approve`, `sim.calibrate`) still work: each prints the
new command and runs it.

**Backends**, wherever a command takes `--backend`:

| Backend | What answers | Needs |
|---|---|---|
| `fake` (default) | Scripted answers: tries the whole pipeline for free | Nothing |
| `lmstudio` | The model loaded in LM Studio (`http://localhost:1234`) | `--model` with the loaded model's id (`lms ps`); see [local models](#local-models) |
| `anthropic` | The Claude API | `ANTHROPIC_API_KEY` in the environment and `--yes-spend` |

---

## commons run

Runs a society with LLM co-ops until a cycle limit, a time limit or a kill-switch. Without `--society` it runs a
pack's live population (two LLM co-ops, a scripted cooperator and the scripted defector).

```sh
uv run commons run --backend fake                                    # free dry run of the whole pipeline
uv run commons run --backend lmstudio --model qwen/qwen3.5-35b-a3b --cycles 10 --serve
uv run commons run --society town-help --backend lmstudio --model <id> --panel --serve
uv run commons run --backend anthropic --yes-spend --real-ceiling 1.00 --cycles 10
```

| Option | Default | Meaning |
|---|---|---|
| `--backend fake\|lmstudio\|anthropic` | `fake` | Who answers (see Backends) |
| `--model ID` | `claude-sonnet-5` on anthropic | The stewards' model; required for LM Studio |
| `--member-model ID` | the steward's model locally; `claude-haiku-4-5` on anthropic | The model members write with |
| `--grader-model ID` | as `--member-model` | The model that grades work and appraises ventures |
| `--yes-spend` | off | Required for `anthropic`: confirms real spending |
| `--pack NAME` | `earn_online` | Which pack (a folder under `packs/`); ignored with `--society` |
| `--society NAME` | none | Runs a founded society from `societies/NAME/`: its pack, seed, brief, approved co-ops, archive, starter playbooks, and its `operator/` folder if present |
| `--operator DIR` | `societies/NAME/operator` if present | Folder of directives, context, limits and the `[gate]` web policy (see `operator.example/`) |
| `--cycles N` | 10 | Stop after N cycles |
| `--max-minutes M` | 30 | Stop after M minutes of wall time (checked between cycles) |
| `--seed N` | 0 (a society's own seed with `--society`) | Random seed: same seed, same jobs |
| `--real-ceiling D` | 1.00 | Real dollars per day before the kill-switch halts everything |
| `--serve` | off | Shows the run on the dashboard at http://localhost:8000; pauses at the cycle limit |
| `--panel` | off | Grades every part with the pack's panel of lenses (median); one call per lens |
| `--rate-every N` | 3 | With `--society`: sets every Nth paid job aside for you to rate |
| `--no-web` | off | No web access, whatever the operator's `[gate]` allows (the fake backend never has web) |
| `--reasoning` | off | For local models that reason first: more room per call (thinking counts against max tokens) |

**Reads:** the pack or society folder; the operator folder (re-read every cycle); `gate.jsonl` and `ratings.jsonl` in
a society folder (re-read every cycle).
**Writes:** to `runs/` (or `societies/NAME/runs/`): the ledger `live-<backend>-<time>.sqlite`, the activity log
`….activity.jsonl` and every LLM turn `….turns.jsonl`. In a society folder: `samples.jsonl` (work to rate),
`gate-requests.jsonl` (requests waiting for you), and pages read from the web under `archive/web/`.
**Safety:** one live run at a time: `runs/live.pid` is a lock. Stop a run with `kill -INT $(cat runs/live.pid)`;
a model call in flight finishes first. Real money needs `--yes-spend`, and the real-dollar kill-switch halts at
`--real-ceiling`. Web reads follow the operator's `[gate]` policy (default: each waits for your approval).

## commons sim

Runs a scripted society (no models, no spend) and prints a summary and its scorecard. This is how incentive rules are
tested: it's deterministic by seed.

```sh
uv run commons sim                     # 200 cycles of pack 0
uv run commons sim 500 --seed 3 --pack tech_for_good
uv run commons sim 200 --no-rep        # control run: reputation off
```

| Option | Default | Meaning |
|---|---|---|
| `cycles` | 200 | How many cycles |
| `--seed N` | 0 | Random seed |
| `--pack NAME` | `earn_online` | Which pack |
| `--no-rep` | off | Control run: reputation disabled (primes can't tell bidders apart) |
| `--no-verify` | off | Skip signature checks on the bus (faster; for experiments only) |

Reads and writes nothing on disk (the ledger is in memory).

## commons found

Founds a society from your brief: one model call drafts the co-ops' blueprints, which you then read, edit and
approve. Founding happens once per society.

```sh
uv run commons found town-help --pack tech_for_good --brief society.tech-for-good.example/brief.md \
    --questions society.tech-for-good.example/questions.md --context society.tech-for-good.example/archive \
    --backend lmstudio --model <id>
# read and edit societies/town-help/blueprints.toml, then:
uv run commons found town-help --approve
```

| Option | Default | Meaning |
|---|---|---|
| `NAME` | required | The society's name: 2 to 24 lowercase letters, digits or hyphens |
| `--approve` | off | Checks the (edited) blueprints against the rules and marks them approved; nothing else |
| `--pack NAME` | `earn_online` | Which pack the society runs on |
| `--brief FILE` | required to found | What the society is for, in your words |
| `--questions FILE` | none | Subjects its work is about, one per line; replace the pack's defaults |
| `--context DIR` | none | Reference files (.md, .txt): summarised for drafting, then copied into the archive |
| `--coops N` | 4 | How many co-ops to draft |
| `--seed N` | 0 | The society's seed, stored in `society.toml` |
| `--backend`, `--model`, `--yes-spend` | `fake` | Who drafts; `fake` writes placeholder co-ops to edit; `--model` defaults to `claude-sonnet-5` on anthropic |
| `--max-tokens N` | 4000 | Room for the drafting call; raise for models that reason first (e.g. 12000) |

**Writes** `societies/NAME/`: `society.toml`, `brief.md`, `questions.md` (if given), `blueprints.toml`
(`approved = false`), `archive/` (a copy of the context). Refuses a folder that already has blueprints.
`--approve` lists errors (which block approval) and warnings (worth reading).
After founding you may add `playbooks/<capability>--<title>.md` (methods seeded into the library) and an `operator/`
folder. `societies/` is git-ignored.

## commons approve

Decides what a running society's agents asked the gate for (today: web searches and page reads), from the command
line. With the dashboard open you can decide there instead.

```sh
uv run commons approve town-help                       # what's waiting, grouped by co-op, tool and host
uv run commons approve town-help --group 1 --always    # approve a group, and that co-op's future reads from that host
uv run commons approve town-help --all
uv run commons approve town-help --id live-lmstudio-20261001-1200/G3 --deny --reason "not relevant"
```

| Option | Meaning |
|---|---|
| `NAME` | The society |
| `--all` | Decide every waiting request |
| `--group N` | Decide numbered group N from the listing (repeatable) |
| `--id ID` | Decide one request by its id (`<run>/G<n>`; repeatable) |
| `--deny` | Deny instead of approve |
| `--always` | With approval: a standing approval for that co-op and host |
| `--reason TEXT` | Told to the co-op with the decision |

**Reads** `gate-requests.jsonl`; **writes** `gate.jsonl` in the society folder. The running society applies decisions
at the start of its next cycle; approved requests run then.

## commons rate

Rates the work a society set aside for you (every Nth paid job, `--rate-every`). Ratings feed the scorecard and
count as reputation evidence about whoever did the work.

```sh
uv run commons rate town-help                 # one piece at a time: 0-3 (optionally a note), s to skip, q to stop
uv run commons rate town-help --list
uv run commons rate town-help --id live-lmstudio-20261001-1200/J12 --rating 2 --note "clear, usable"
```

| Option | Meaning |
|---|---|
| `NAME` | The society |
| `--list` | Show what's waiting |
| `--id ID --rating N` | Rate one piece without the prompt (both required together) |
| `--note TEXT` | A note with the rating |

Ratings: 0 wrong or harmful · 1 not useful · 2 useful · 3 very useful. **Reads** `samples.jsonl`; **writes**
`ratings.jsonl` in the society folder; a running society picks new ratings up at its next cycle.

## commons calibrate

Runs a grader (or the venture appraiser) over a pack's hand-labelled cases and reports agreement, and whether the
manipulation case was resisted. Do this before trusting a model as a grader.

```sh
uv run commons calibrate --pack tech_for_good                       # fake oracle: checks the plumbing only
uv run commons calibrate --pack tech_for_good --backend lmstudio --model <id> --max-tokens 12000
uv run commons calibrate --pack tech_for_good --backend lmstudio --model <id> --max-tokens 12000 --panel
uv run commons calibrate --pack tech_for_good --target appraiser --backend lmstudio --model <id> --max-tokens 12000
```

| Option | Default | Meaning |
|---|---|---|
| `--pack NAME` | `earn_online` | Whose cases and instructions |
| `--target grader\|appraiser` | `grader` | What to check |
| `--panel` | off | Grade with the pack's panel of lenses (median), as `commons run --panel` does |
| `--backend`, `--model`, `--yes-spend` | `fake` | `fake` is an oracle that knows the answers; `--model` defaults to `claude-haiku-4-5` on anthropic |
| `--max-tokens N` | 400 | Room per call; raise for models that reason first (12000 for Qwen 3.5) |

Writes nothing. Last results: see `docs/CHECKLIST.md`.

## The dashboard

`commons run --serve` shows a live run. To watch a scripted society instead:

```sh
uv run uvicorn commons.interfaces.console.app:app      # http://localhost:8000; Ctrl-C to stop
```

The page has controls (pause, resume, step, speed, pull and reset the kill-switch), every component's panel, the scorecard, the
Gate panel (approve requests in batches, standing approvals, revoke) and the Operator panel (edit directives live).
It pauses itself if its process passes 2 GB.

## Tests

```sh
uv run pytest                          # everything (about 35 s), golden master included
uv run pytest -m golden                # only the golden master (8 runs, about 5 s)
uv run pytest tests/test_layers.py     # only the dependency rule
uv run python -m tests.golden.update   # regenerate the golden fixtures: only after an approved behaviour change
```

Commit only when pytest itself exits 0 (`uv run pytest -q > runs/pytest.log 2>&1; rc=$?`), never through a pipe,
which hides failures. After a deliberate mutation test, delete `__pycache__` before trusting the next run.

## Architecture metrics

```sh
uv run python -m tools.arch_metrics
```

Prints the measurements behind `docs/ARCHITECTURE-AUDIT.md` (sizes, cycles, long functions, hidden imports, status
strings, economy checks, private access). Re-run after every refactor stage.

## Local models

The machine has 48 GB; only one heavy thing at a time (a live run, the dashboard, or a model). Check before loading
and unload afterwards:

```sh
~/.lmstudio/bin/lms ps                       # what's loaded
memory_pressure | tail -1                    # free memory
~/.lmstudio/bin/lms server start
~/.lmstudio/bin/lms load qwen/qwen3.5-35b-a3b --context-length 32768 -y      # about 21 GB
~/.lmstudio/bin/lms unload --all; ~/.lmstudio/bin/lms server stop
```
