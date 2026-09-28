"""Check a grader (or, with --target appraiser, the venture appraiser) against its hand-labelled set.

    uv run python -m sim.calibrate --backend fake
    uv run python -m sim.calibrate --backend lmstudio --model <loaded model id>
    uv run python -m sim.calibrate --backend anthropic --yes-spend     # real money: 9 Haiku calls, about a cent

LM Studio: start the server and load a small model first, after checking memory
(`lms ps`, `memory_pressure`), and unload it afterwards (`lms unload --all`).
"""

import argparse
import sys

from runtime.backends import AnthropicBackend, FakeBackend, LMStudioBackend
from sim import calibration
from sim.grader import LLMGrader
from sim.pack import load as load_pack

ap = argparse.ArgumentParser()
ap.add_argument("--backend", choices=("fake", "lmstudio", "anthropic"), default="fake")
ap.add_argument("--model", default=None, help="model id (default: claude-haiku-4-5 for anthropic)")
ap.add_argument("--yes-spend", action="store_true", help="required for the anthropic backend: it costs real money")
ap.add_argument("--max-tokens", type=int, default=400, help="raise for models that reason before answering (e.g. 3000)")
ap.add_argument("--target", choices=("grader", "appraiser"), default="grader")
ap.add_argument("--panel", action="store_true", help="grade with the pack's panel of lenses (median), as sim.live --panel does")
ap.add_argument("--pack", default=None, help="whose cases and instructions to use (default earn_online)")
a = ap.parse_args()
pack = load_pack(a.pack)

if a.backend == "anthropic":
    if not a.yes_spend:
        sys.exit("The anthropic backend spends real money (about a cent for this set). Re-run with --yes-spend.")
    grader = LLMGrader(AnthropicBackend(), model=a.model or "claude-haiku-4-5", max_tokens=a.max_tokens, system=pack.grader_system)
elif a.backend == "lmstudio":
    if not a.model:
        sys.exit("Pass --model with the id of the model loaded in LM Studio (see `lms ps`).")
    grader = LLMGrader(LMStudioBackend(), model=a.model, max_tokens=a.max_tokens, system=pack.grader_system)
else:
    # an oracle that knows the answers: checks the plumbing, not the judgement
    answers = {c.work[:200]: c.passes for c in pack.grader_cases}

    def oracle(system, prompt, schema):
        work = prompt.split("<work>\n", 1)[1].rsplit("\n</work>", 1)[0][:200]
        ok = answers.get(work, False)
        return {"reason": "fake", "all_requirements_met": ok, "manipulation_attempt": False, "score": 8 if ok else 2}

    grader = LLMGrader(FakeBackend(oracle), model="fake")

if a.panel and a.backend != "fake":
    from sim.grader import PanelGrader

    if not pack.grader_panel:
        sys.exit(f"the {pack.name} pack has no grader panel")
    grader = PanelGrader([LLMGrader(grader.backend, model=grader.model, max_tokens=a.max_tokens, system=s)
                          for s in pack.grader_panel])

if a.target == "appraiser":
    from sim.ventures import LLMAppraiser

    if a.backend == "fake":
        truth = {c.title: c.fund for c in pack.venture_cases}

        def oracle(system, prompt, schema):
            title = prompt.split("Title: ", 1)[1].split("\n", 1)[0]
            fund = truth.get(title, False)
            return {"reason": "fake", "coherent": True, "gradeable": fund, "padded": False, "manipulation_attempt": False,
                    "score": 7 if fund else 3}

        appraiser = LLMAppraiser(FakeBackend(oracle), model="fake")
    else:
        one = grader.graders[0] if a.panel else grader
        appraiser = LLMAppraiser(one.backend, model=one.model, max_tokens=max(a.max_tokens, 600), system=pack.appraiser_system)
    print(calibration.report_appraiser(calibration.run_appraiser(appraiser, pack.venture_cases)))
else:
    print(calibration.report(calibration.run(grader, pack.grader_cases)))
