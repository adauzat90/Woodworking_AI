"""Tests for planning.py — skill rating + method-aware build time.

Pure math; runs without build123d or an API key.
"""

import pytest

from woodworking_ai import (
    CabinetSpec, TableSpec, Material, ToeKick, Drawer,
    Joinery, CornerJoint,
)
from woodworking_ai.tooling import HAND_TOOL_SHOP, FULL_SHOP
from woodworking_ai.planning import skill, build_time, plan


def base_spec(**o) -> CabinetSpec:
    d = dict(name="Test", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def dovetail_drawer_spec(**o) -> CabinetSpec:
    """A cabinet with two dovetailed drawer boxes — the hand-joinery case."""
    d = dict(doors=0, drawers=[
        Drawer(front_height=140, corner_joint=CornerJoint.DOVETAIL),
        Drawer(front_height=200, corner_joint=CornerJoint.DOVETAIL),
    ])
    d.update(o)
    return base_spec(**d)


# === build_time: hand tools cost more than a full shop, same spec ==========

def test_hand_tools_cost_more_total_than_full_shop():
    spec = dovetail_drawer_spec()
    hand = build_time(spec, HAND_TOOL_SHOP)
    full = build_time(spec, FULL_SHOP)
    assert hand["total"] > full["total"]


def test_hand_tools_cost_more_for_a_plain_cabinet_too():
    spec = base_spec()   # dados, rabbets, hinge cups, shelf pins
    hand = build_time(spec, HAND_TOOL_SHOP)
    full = build_time(spec, FULL_SHOP)
    assert hand["total"] > full["total"]
    # The joinery phase in particular is where hand work blows up.
    assert (hand["hours_by_phase"]["joinery"]
            > full["hours_by_phase"]["joinery"])


def test_dovetails_joinery_phase_dominated_by_hand():
    spec = dovetail_drawer_spec()
    hand = build_time(spec, HAND_TOOL_SHOP)
    full = build_time(spec, FULL_SHOP)
    # Two hand-cut dovetailed boxes are dramatically slower than the machine path.
    assert (hand["hours_by_phase"]["joinery"]
            >= 2 * full["hours_by_phase"]["joinery"])


# === build_time: structure + stability =====================================

def test_phases_present_and_total_consistent():
    spec = base_spec()
    bt = build_time(spec, FULL_SHOP)
    for p in ("mill", "joinery", "assembly", "finish", "hardware"):
        assert p in bt["hours_by_phase"]
    assert bt["total"] == pytest.approx(
        sum(bt["hours_by_phase"].values()), abs=0.05)
    assert bt["total"] > 0
    assert bt["drivers"]


def test_no_tooling_path_works_and_is_stable():
    spec = base_spec()
    a = build_time(spec)            # tooling=None
    b = build_time(spec, None)
    assert a == b                    # deterministic / stable
    assert a["total"] > 0
    # A well-equipped default should land at or below the hand-tool cost.
    assert a["total"] <= build_time(spec, HAND_TOOL_SHOP)["total"]


def test_finish_adds_finish_phase_time():
    plain = build_time(base_spec(finish="none"), FULL_SHOP)
    oiled = build_time(base_spec(finish="oil"), FULL_SHOP)
    assert oiled["hours_by_phase"]["finish"] > plain["hours_by_phase"]["finish"]
    assert oiled["total"] > plain["total"]


def test_table_build_time_runs():
    bt = build_time(TableSpec(joinery=Joinery.MORTISE_TENON), HAND_TOOL_SHOP)
    assert bt["total"] > 0
    assert bt["hours_by_phase"]["joinery"] > 0


# === skill: escalation on hand joinery =====================================

def test_dovetail_drawers_are_advanced():
    s = skill(dovetail_drawer_spec())
    assert s["level"] == "advanced"
    assert any("dovetail" in d for d in s["drivers"])


def test_mortise_tenon_table_is_advanced_or_above_beginner():
    s = skill(TableSpec(joinery=Joinery.MORTISE_TENON))
    assert s["level"] == "advanced"
    assert any("mortise-tenon" in d for d in s["drivers"])


def test_simple_screwed_cabinet_is_not_advanced():
    s = skill(base_spec(joinery=Joinery.SCREW, doors=1, shelves=0,
                        finish="none"))
    assert s["level"] in ("beginner", "intermediate")
    assert s["level"] != "advanced"


def test_skill_always_lists_drivers():
    s = skill(base_spec())
    assert isinstance(s["drivers"], list) and s["drivers"]


# === plan() wrapper ========================================================

def test_plan_bundles_skill_and_time():
    p = plan(base_spec(), FULL_SHOP)
    assert set(p) == {"skill", "time"}
    assert p["skill"]["level"] in ("beginner", "intermediate", "advanced")
    assert p["time"]["total"] > 0


def test_plan_is_json_friendly():
    import json
    json.dumps(plan(dovetail_drawer_spec(), HAND_TOOL_SHOP))
