"""The refusal suite: the system must FLAG an infeasible request, never silently
accept it. Deterministic (validator + critic), no API key.

These tests lock in the current coverage — every case meets its expected minimum
severity — so a future change that lets an infeasible spec validate clean (or
downgrades a hard error to nothing) fails CI.
"""

import json
import pathlib

import pytest

from woodworking_ai.designer_eval import (
    REFUSAL_CASES, RefusalCase, score_refusal, run_refusal_eval,
    _ref_cab,
)

EVALS = pathlib.Path(__file__).resolve().parent.parent / "evals"


@pytest.mark.parametrize("case", REFUSAL_CASES, ids=[c.name for c in REFUSAL_CASES])
def test_case_is_flagged_to_expectation(case):
    res = score_refusal(case)
    assert res.passed, (
        f"{case.name}: expected >= {case.expect} but the system was "
        f"'{res.severity}' (should flag: {case.concern})")
    # nothing in this suite may be silently accepted
    assert res.severity != "silent"


def test_expected_hard_errors_really_error():
    by_name = {c.name: c for c in REFUSAL_CASES}
    for name in ("negative_width", "zero_height", "over_max_dimension",
                 "too_many_shelves", "drawer_taller_than_box"):
        assert score_refusal(by_name[name]).severity in ("error", "parse-error")


def test_three_metre_cabinet_is_at_least_warned():
    case = next(c for c in REFUSAL_CASES if c.name == "three_metre_single_cabinet")
    res = score_refusal(case)
    assert res.severity in ("error", "warning")
    assert res.passed


def test_silent_case_would_fail():
    """A request the system does NOT flag must score as a failure."""
    sane = RefusalCase("totally_fine", "a normal 600mm base cabinet",
                       lambda: _ref_cab(width=600, shelves=1, doors=2),
                       "flagged", "nothing — this one is fine")
    res = score_refusal(sane)
    assert res.severity == "silent"
    assert res.passed is False


def test_report_rates_and_format():
    rep = run_refusal_eval()
    assert rep.total == len(REFUSAL_CASES)
    assert rep.pass_rate == 1.0          # current coverage: all flagged to spec
    assert rep.flag_rate == 1.0          # none silently accepted
    assert 0.0 < rep.hard_block_rate < 1.0   # a documented mix of error vs warning
    assert "Refusal suite" in rep.format()


def test_committed_refusal_json_matches():
    committed = json.loads((EVALS / "refusal.json").read_text(encoding="utf-8"))
    rep = run_refusal_eval().to_dict()
    # compare structural fields (not the free-text validator messages)
    for k in ("pass_rate", "flag_rate", "hard_block_rate", "total", "passed"):
        assert committed[k] == rep[k], k
    got = {c["name"]: (c["severity"], c["passed"], c["expect"]) for c in rep["cases"]}
    want = {c["name"]: (c["severity"], c["passed"], c["expect"])
            for c in committed["cases"]}
    assert got == want
