"""Headless tests for the designer accuracy harness.

The agent-calling part (``run_eval``) needs an API key, but the *scoring* is
pure: it runs against a hand-built spec with real ``validate``/``critique`` and
no network. These tests pin that scoring, the pass/fail verdict, the report
aggregation, and the agent-failure path.
"""

import pytest

from woodworking_ai import CabinetSpec, Drawer
from woodworking_ai.dsl import TableSpec
from woodworking_ai.validator import validate, ValidationResult, Issue
from woodworking_ai.agents.critic import critique
from woodworking_ai.designer_eval import (
    EvalCase, IntentCheck, CaseResult, EvalReport,
    cabinet_type_is, is_table, dim_near, doors_eq, drawers_eq, drawers_at_least,
    shelves_at_least, dim_between, door_style_is, construction_is,
    no_toe_kick, drawer_front_heights, all_drawers_attr,
    cabinet_type_in, has_storage, is_project, component_count,
    component_widths_include, all_components_type,
    score_spec, _failure_result,
    DEFAULT_CASES, ADVERSARIAL_CASES, STRESS_CASES,
    AMBIGUOUS_CASES, PROJECT_CASES, SUITES,
)
from woodworking_ai import Project, place_run


# --- predicates are robust to the wrong spec type (return False, never raise) --

def test_predicates_dont_raise_on_wrong_type():
    table = TableSpec(name="t", width=1200, depth=600, height=450)
    cab = CabinetSpec(name="c", width=600, height=720, depth=560)
    assert is_table()(table) is True
    assert is_table()(cab) is False
    assert cabinet_type_is("base")(table) is False     # no cabinet_type on a table
    assert dim_near("nonexistent", 100)(cab) is False  # missing attr -> False


def test_dim_near_tolerance():
    cab = CabinetSpec(name="c", width=900, height=720, depth=560)
    assert dim_near("width", 914, tol=20)(cab) is True    # 36" rounded to 900
    assert dim_near("width", 914, tol=5)(cab) is False


# --- the deterministic scoring core -----------------------------------------

SINK_CASE = EvalCase(
    "sink_base",
    "36in base, two shaker doors, one shelf",
    (
        IntentCheck("base", cabinet_type_is("base")),
        IntentCheck("~36in", dim_near("width", 914, tol=20)),
        IntentCheck("two doors", doors_eq(2)),
        IntentCheck("shaker", door_style_is("shaker")),
        IntentCheck("a shelf", shelves_at_least(1)),
    ),
)


def _good_sink():
    return CabinetSpec(name="Sink", width=900, height=720, depth=560,
                       doors=2, shelves=1, door_style="shaker")


def test_matching_spec_passes_with_full_intent():
    spec = _good_sink()
    res = score_spec(SINK_CASE, spec, validate(spec), critique(spec))
    assert res.passed is True
    assert res.buildable is True
    assert res.intents_passed == res.intents_total == 5
    assert res.required_missed == []


def test_wrong_door_count_fails_the_required_intent():
    spec = CabinetSpec(name="Sink", width=900, height=720, depth=560,
                       doors=1, shelves=1, door_style="shaker")
    res = score_spec(SINK_CASE, spec, validate(spec), critique(spec))
    assert res.passed is False
    assert "two doors" in res.required_missed
    assert res.intents_passed == 4   # the other four still hold


def test_unbuildable_spec_fails_even_with_full_intent():
    """A validation error gates the verdict regardless of intent match."""
    spec = _good_sink()
    broken = ValidationResult(issues=[Issue("error", "width", "forced failure")])
    res = score_spec(SINK_CASE, spec, broken, crit=None)
    assert res.buildable is False
    assert res.passed is False
    assert res.intents_passed == 5            # intent still measured…
    assert res.validation_errors == ["[error] width: forced failure"]  # …but reported


def test_optional_intent_never_fails_a_case():
    case = EvalCase("opt", "p", (
        IntentCheck("base", cabinet_type_is("base")),
        IntentCheck("nice to have", drawers_eq(3), required=False),
    ))
    spec = _good_sink()  # a base with no drawers
    res = score_spec(case, spec, validate(spec), critique(spec))
    assert res.passed is True
    assert res.optional_missed == ["nice to have"]
    assert res.required_missed == []


def test_drawer_base_intents():
    case = EvalCase("db", "30in 3-drawer base, no doors", (
        IntentCheck("base", cabinet_type_is("base")),
        IntentCheck("three drawers", drawers_eq(3)),
        IntentCheck("no doors", doors_eq(0)),
    ))
    spec = CabinetSpec(name="DB", width=762, height=720, depth=560, doors=0,
                       drawers=[Drawer(160), Drawer(160), Drawer(200)])
    res = score_spec(case, spec, validate(spec), critique(spec))
    assert res.passed is True
    assert res.intents_passed == 3


def test_faceframe_and_construction_predicate():
    spec = CabinetSpec(name="BC", width=900, height=1800, depth=300,
                       cabinet_type="bookcase", construction="face_frame",
                       shelves=4, doors=0)
    assert construction_is("face_frame")(spec) is True
    assert cabinet_type_is("bookcase")(spec) is True
    assert shelves_at_least(4)(spec) is True


# --- report aggregation ------------------------------------------------------

def _cr(name, passed, buildable, ip, it):
    # A non-passing case carries a required miss so .passed is False even when
    # the spec was buildable (an intent disagreement, not a build failure).
    missed = [] if passed else ["x"]
    return CaseResult(name=name, prompt="", buildable=buildable,
                      intents_passed=ip, intents_total=it, required_missed=missed)


def test_report_rates():
    results = [
        _cr("a", True, True, 3, 3),
        _cr("b", False, True, 1, 3),     # buildable, intent miss -> fail
        _cr("c", False, False, 0, 3),    # not buildable -> fail
    ]
    rep = EvalReport(results)
    assert rep.total == 3
    assert rep.pass_rate == pytest.approx(1 / 3)
    assert rep.buildable_rate == pytest.approx(2 / 3)
    assert rep.intent_rate == pytest.approx((1 + 1 / 3 + 0) / 3)


def test_report_to_dict_and_format():
    rep = EvalReport([_cr("a", True, True, 3, 3)])
    d = rep.to_dict()
    assert d["pass_rate"] == 1.0 and d["total"] == 1
    assert d["cases"][0]["name"] == "a"
    text = rep.format()
    assert "PASS" in text and "pass rate" in text


def test_empty_report_is_safe():
    rep = EvalReport([])
    assert rep.pass_rate == 0.0 and rep.buildable_rate == 0.0


# --- agent-failure path ------------------------------------------------------

def test_failure_result_records_error_and_fails():
    res = _failure_result(SINK_CASE, "RuntimeError: boom")
    assert res.passed is False
    assert res.buildable is False
    assert res.error == "RuntimeError: boom"
    # every required intent is recorded as missed for visibility
    assert "two doors" in res.required_missed


# --- the shipped dataset is well-formed --------------------------------------

@pytest.mark.parametrize("cases", [DEFAULT_CASES, ADVERSARIAL_CASES, STRESS_CASES,
                                   AMBIGUOUS_CASES, PROJECT_CASES])
def test_cases_are_well_formed(cases):
    names = [c.name for c in cases]
    assert len(names) == len(set(names))          # unique names
    assert len(cases) >= 3
    for c in cases:
        assert c.prompt and c.intents
        assert any(ic.required for ic in c.intents)


def test_suites_registry():
    assert set(SUITES) == {"default", "adversarial", "stress",
                           "ambiguous", "projects", "all"}
    assert SUITES["all"] == (DEFAULT_CASES + ADVERSARIAL_CASES + STRESS_CASES
                             + AMBIGUOUS_CASES + PROJECT_CASES)
    # every case name is globally unique across suites
    names = [c.name for c in SUITES["all"]]
    assert len(names) == len(set(names))


def test_ambiguous_predicates():
    cab = CabinetSpec(name="c", width=600, height=720, depth=560,
                      cabinet_type="wall", shelves=2)
    assert cabinet_type_in(["base", "wall", "tall"])(cab) is True
    assert cabinet_type_in(["base", "tall"])(cab) is False
    assert has_storage()(cab) is True
    bare = CabinetSpec(name="x", width=600, height=720, depth=560,
                       doors=0, shelves=0)
    assert has_storage()(bare) is False


def test_project_predicates():
    proj = Project(name="run", components=place_run(
        [CabinetSpec(width=900, cabinet_type="base"),
         CabinetSpec(width=600, cabinet_type="base"),
         CabinetSpec(width=450, cabinet_type="base")], start=(0, 0), angle=0))
    cab = CabinetSpec(name="c", width=600, height=720, depth=560)
    assert is_project()(proj) is True
    assert is_project()(cab) is False
    assert component_count(3)(proj) is True
    assert component_count(2)(proj) is False
    assert all_components_type("base")(proj) is True
    assert all_components_type("wall")(proj) is False
    assert component_widths_include([900, 600, 450])(proj) is True
    assert component_widths_include([900, 900])(proj) is False  # only one 900
    # predicates return False (not raise) on a non-project spec
    assert component_count(1)(cab) is False
    assert all_components_type("base")(cab) is False


def test_stress_predicates():
    spec = CabinetSpec(name="DB", width=600, height=720, depth=560, doors=0,
                       toe_kick=None,
                       drawers=[Drawer(140), Drawer(180), Drawer(180),
                                Drawer(220, slide_type="undermount")])
    assert no_toe_kick()(spec) is True
    assert drawer_front_heights([220, 180, 140, 180])(spec) is True   # order-free
    assert drawer_front_heights([140, 180, 180, 200])(spec) is False  # 220 != 200
    # not every drawer is undermount here
    assert all_drawers_attr("slide_type", "undermount")(spec) is False
    allu = CabinetSpec(name="x", width=600, height=720, depth=560, doors=0,
                       drawers=[Drawer(160, slide_type="undermount"),
                                Drawer(160, slide_type="undermount")])
    assert all_drawers_attr("slide_type", "undermount")(allu) is True
    assert all_drawers_attr("corner_joint", "dovetail")(allu) is True  # default


def test_new_predicates():
    cab = CabinetSpec(name="c", width=600, height=720, depth=560,
                      drawers=[Drawer(160), Drawer(160), Drawer(160), Drawer(160)])
    assert drawers_at_least(4)(cab) is True
    assert drawers_at_least(5)(cab) is False
    assert dim_between("height", 700, 740)(cab) is True
    assert dim_between("height", 100, 200)(cab) is False
    assert dim_between("missing", 0, 10)(cab) is False
