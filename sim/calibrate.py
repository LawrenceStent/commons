"""Check a grader (or, with --target appraiser, the venture appraiser) against its hand-labelled set.

    uv run python -m sim.calibrate --backend fake
    uv run python -m sim.calibrate --backend lmstudio --model <loaded model id>
    uv run python -m sim.calibrate --backend anthropic --yes-spend     # real money: 9 Haiku calls, about a cent

LM Studio: start the server and load a small model first, after checking memory
(`lms ps`, `memory_pressure`), and unload it afterwards (`lms unload --all`).
"""

import argparse
import sys

from runtime.backends import BackendChoiceError, FakeBackend, add_backend_args, choose_backend
from sim import calibration
from sim.grader import LLMGrader
from sim.pack import load as load_pack

ap = argparse.ArgumentParser()
add_backend_args(ap, "model id (default: claude-haiku-4-5 for anthropic)")
ap.add_argument("--max-tokens", type=int, default=400, help="raise for models that reason before answering (e.g. 3000)")
ap.add_argument("--target", choices=("grader", "appraiser"), default="grader")
ap.add_argument("--panel", action="store_true", help="grade with the pack's panel of lenses (median), as sim.live --panel does")
ap.add_argument("--pack", default=None, help="whose cases and instructions to use (default earn_online)")
a = ap.parse_args()
pack = load_pack(a.pack)

# --backend fake: an oracle that knows the answers. It checks the plumbing, not the judgement.
answers = {c.work[:200]: c.passes for c in pack.grader_cases}


def grade_oracle(system, prompt, schema):
    work = prompt.split("<work>\n", 1)[1].rsplit("\n</work>", 1)[0][:200]
    ok = answers.get(work, False)
    return {"reason": "fake", "all_requirements_met": ok, "manipulation_attempt": False, "score": 8 if ok else 2}


try:
    backend, model = choose_backend(a.backend, a.model, a.yes_spend, default_model="claude-haiku-4-5",
                                    fake=lambda: FakeBackend(grade_oracle), cost="about a cent for this set")
except BackendChoiceError as e:
    sys.exit(str(e))
grader = LLMGrader(backend, model=model, max_tokens=a.max_tokens, system=pack.grader_system)

if a.panel and a.backend != "fake":
    from sim.grader import PanelGrader

    if not pack.grader_panel:
        sys.exit(f"the {pack.name} pack has no grader panel")
    grader = PanelGrader.of(backend, model, a.max_tokens, pack.grader_system, pack.grader_panel)

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
