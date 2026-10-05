"""Check a grader (or, with --target appraiser, the venture appraiser) against its hand-labelled set.

    uv run commons calibrate --backend fake
    uv run commons calibrate --backend lmstudio --model <loaded model id>
    uv run commons calibrate --backend anthropic --yes-spend     # real money: 9 Haiku calls, about a cent

LM Studio: start the server and load a small model first, after checking memory
(`lms ps`, `memory_pressure`), and unload it afterwards (`lms unload --all`).
"""

import argparse
import sys

from commons.adapters.models import BackendChoiceError, FakeBackend, add_backend_args, choose_backend
from commons.application import calibration
from commons.application.graders import LLMGrader, PanelGrader
from commons.application.ventures import LLMAppraiser
from commons.domain.pack import load as load_pack


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="commons calibrate", description="check a grader or appraiser against its cases")
    add_backend_args(ap, "model id (default: claude-haiku-4-5 for anthropic)")
    ap.add_argument("--max-tokens", type=int, default=400, help="raise for models that reason before answering (e.g. 3000)")
    ap.add_argument("--target", choices=("grader", "appraiser"), default="grader", help="what to check")
    ap.add_argument("--panel", action="store_true", help="grade with the pack's panel of lenses (median), as commons run --panel does")
    ap.add_argument("--pack", default=None, help="whose cases and instructions to use (default earn_online)")
    return ap


def grade_oracle(pack):
    """--backend fake: an oracle that knows the answers. It checks the plumbing, not the judgement."""
    answers = {c.work[:200]: c.passes for c in pack.grader_cases}

    def respond(system, prompt, schema):
        ok = answers.get(prompt.split("<work>\n", 1)[1].rsplit("\n</work>", 1)[0][:200], False)
        return {"reason": "fake", "all_requirements_met": ok, "manipulation_attempt": False, "score": 8 if ok else 2}
    return respond


def appraise_oracle(pack):
    truth = {c.title: c.fund for c in pack.venture_cases}

    def respond(system, prompt, schema):
        fund = truth.get(prompt.split("Title: ", 1)[1].split("\n", 1)[0], False)
        return {"reason": "fake", "coherent": True, "gradeable": fund, "padded": False, "manipulation_attempt": False,
                "score": 7 if fund else 3}
    return respond


def grader_for(a, pack):
    try:
        backend, model = choose_backend(a.backend, a.model, a.yes_spend, default_model="claude-haiku-4-5",
                                        fake=lambda: FakeBackend(grade_oracle(pack)), cost="about a cent for this set")
    except BackendChoiceError as e:
        sys.exit(str(e))
    if a.panel and a.backend != "fake":
        if not pack.grader_panel:
            sys.exit(f"the {pack.name} pack has no grader panel")
        return PanelGrader.of(backend, model, a.max_tokens, pack.grader_system, pack.grader_panel)
    return LLMGrader(backend, model=model, max_tokens=a.max_tokens, system=pack.grader_system)


def main(argv: list[str] | None = None) -> None:
    a = parser().parse_args(argv)
    pack = load_pack(a.pack)
    grader = grader_for(a, pack)
    if a.target == "grader":
        return print(calibration.report(calibration.run(grader, pack.grader_cases)))
    if a.backend == "fake":
        appraiser = LLMAppraiser(FakeBackend(appraise_oracle(pack)), model="fake")
    else:
        one = grader.graders[0] if isinstance(grader, PanelGrader) else grader
        appraiser = LLMAppraiser(one.backend, model=one.model, max_tokens=max(a.max_tokens, 600), system=pack.appraiser_system)
    print(calibration.report_appraiser(calibration.run_appraiser(appraiser, pack.venture_cases)))


if __name__ == "__main__":
    main()
