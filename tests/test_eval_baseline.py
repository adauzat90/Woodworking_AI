"""Regression guard for the checked-in designer-eval baseline (no API key).

`evals/specs/<suite>/<case>.json` are real specs produced by the designer for
each eval prompt; `evals/baseline.json` records their measured scores. These
tests re-score the committed specs with the shipped harness so a change to the
validator, critic, or intent checks that would regress the baseline is caught in
CI — without calling the agent.
"""

import json
import pathlib

import pytest

from woodworking_ai.dsl import spec_from_dict
from woodworking_ai.validator import validate
from woodworking_ai.agents.critic import critique
from woodworking_ai.designer_eval import SUITES, score_spec

EVALS = pathlib.Path(__file__).resolve().parent.parent / "evals"
SPECS = EVALS / "specs"


BASELINE_SUITES = ("default", "adversarial", "stress", "ambiguous", "projects")


def _cases():
    for suite in BASELINE_SUITES:
        for case in SUITES[suite]:
            yield suite, case


@pytest.mark.parametrize("suite,case", list(_cases()),
                         ids=[f"{s}:{c.name}" for s, c in _cases()])
def test_committed_spec_still_passes(suite, case):
    path = SPECS / suite / f"{case.name}.json"
    assert path.exists(), f"missing committed spec for {case.name}"
    raw = json.loads(path.read_text(encoding="utf-8"))
    spec = spec_from_dict(raw)
    res = score_spec(case, spec, validate(spec), critique(spec))
    assert res.buildable, f"{case.name} no longer builds: {res.validation_errors + res.critic_errors}"
    assert res.passed, f"{case.name} missed required intent(s): {res.required_missed}"


def test_baseline_json_matches_committed_specs():
    baseline = json.loads((EVALS / "baseline.json").read_text(encoding="utf-8"))
    agg = baseline["aggregate"]
    # The fixtures are a clean 16/16 snapshot; assert the recorded number is
    # exactly what re-scoring the committed specs yields.
    passed = 0
    total = 0
    for suite in BASELINE_SUITES:
        for case in SUITES[suite]:
            raw = json.loads((SPECS / suite / f"{case.name}.json").read_text())
            spec = spec_from_dict(raw)
            res = score_spec(case, spec, validate(spec), critique(spec))
            passed += int(res.passed)
            total += 1
    assert total == agg["total"]
    assert passed == agg["passed"]
