"""Tests for the final catalog rules: STRUCT-012 (dovetail orientation) and
DIM-009 (32mm-system shelf-pin feasibility), plus the grid_violations guard."""

from woodworking_ai import (
    CabinetSpec, CabinetType, ToeKick, Drawer, validate,
    drilling_schedule, grid_violations,
)
from woodworking_ai.drilling import DrillingSchedule, DrillOp, Hole


def cab(**o) -> CabinetSpec:
    d = dict(name="C", cabinet_type=CabinetType.BASE, width=600, height=720,
             depth=560, shelves=1, doors=0, toe_kick=ToeKick(100, 50))
    d.update(o)
    return CabinetSpec(**d)


def dresser(**o) -> CabinetSpec:
    d = dict(name="D", cabinet_type=CabinetType.DRESSER, width=900, height=800,
             depth=500, shelves=0, doors=0, anti_tip=True,
             toe_kick=ToeKick(100, 50))
    d.update(o)
    return CabinetSpec(**d)


# --- STRUCT-012: dovetail orientation ------------------------------------

def test_dovetail_tails_on_front_errors():
    spec = dresser(drawers=[Drawer(160, corner_joint="dovetail",
                                   dovetail_tails="front")])
    r = validate(spec)
    assert not r.ok
    assert any("tails" in e.message for e in r.errors)


def test_dovetail_tails_on_sides_ok():
    spec = dresser(drawers=[Drawer(160, corner_joint="dovetail",
                                   dovetail_tails="sides")])
    assert not any("tails" in i.message for i in validate(spec).issues)


def test_default_dovetail_drawer_is_oriented_correctly():
    assert not any("tails" in i.message
                   for i in validate(dresser(drawers=[Drawer(160)])).issues)


def test_tails_field_ignored_for_non_dovetail_joint():
    # A box joint isn't a dovetail, so its tail orientation is irrelevant.
    spec = dresser(drawers=[Drawer(160, corner_joint="box",
                                   dovetail_tails="front")])
    assert not any("tails" in i.message for i in validate(spec).issues)


# --- DIM-009: 32mm shelf-pin feasibility ---------------------------------

def test_too_short_for_pin_column_warns():
    spec = cab(height=250, toe_kick=ToeKick(80, 50))  # ~170mm box
    assert any(w.field == "shelves" and "32mm" in w.message
               for w in validate(spec).warnings)


def test_too_shallow_for_pin_rows_warns():
    spec = cab(depth=70)
    assert any(w.field == "depth" and "32mm" in w.message
               for w in validate(spec).warnings)


def test_normal_cabinet_drills_cleanly():
    msgs = [w.message for w in validate(cab()).warnings if "32mm" in w.message]
    assert msgs == []


def test_no_pin_checks_without_shelves():
    assert not any("32mm" in w.message
                   for w in validate(cab(shelves=0)).warnings)


# --- grid_violations guard -----------------------------------------------

def test_real_schedule_is_grid_clean():
    sched = drilling_schedule(cab(shelves=3))
    assert grid_violations(sched) == []


def test_off_grid_schedule_is_flagged():
    bad = DrillingSchedule(spec_name="bad")
    op = DrillOp(part="Side", operation="shelf-pin holes (32mm)")
    # 40mm gap (not 32) and a wrong 6mm pin diameter.
    op.holes = [Hole("front row", 37.0, 64.0, 6.0, 12.0),
                Hole("front row", 37.0, 104.0, 6.0, 12.0)]
    bad.ops.append(op)
    violations = grid_violations(bad)
    assert any("grid" in v for v in violations)
    assert any("dia" in v for v in violations)
