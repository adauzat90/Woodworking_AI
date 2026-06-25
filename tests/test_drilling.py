"""Tests for the drilling schedule (32mm system, hinges, slides)."""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer,
    drilling_schedule, hinge_count,
)
from woodworking_ai.drilling import SYSTEM_PITCH, PIN_DIA, HINGE_CUP_DIA


def spec(**o) -> CabinetSpec:
    d = dict(name="Drill", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- shelf pins ----------------------------------------------------------

def test_two_pin_rows_per_side():
    sched = drilling_schedule(spec(shelves=1))
    pin_ops = [op for op in sched.ops if "shelf-pin" in op.operation]
    assert len(pin_ops) == 2  # one op per side
    rows = {h.face for op in pin_ops for h in op.holes}
    assert rows == {"front row", "back row"}


def test_pin_holes_are_on_32mm_pitch():
    sched = drilling_schedule(spec(shelves=2))
    op = next(o for o in sched.ops if "shelf-pin" in o.operation)
    fronts = sorted(h.v for h in op.holes if h.face == "front row")
    gaps = {round(b - a, 1) for a, b in zip(fronts, fronts[1:])}
    assert gaps == {SYSTEM_PITCH}
    assert all(h.dia == PIN_DIA for h in op.holes)


def test_no_pin_holes_without_shelves():
    sched = drilling_schedule(spec(shelves=0))
    assert not any("shelf-pin" in op.operation for op in sched.ops)


# --- hinges --------------------------------------------------------------

@pytest.mark.parametrize("h,n", [(700, 2), (1200, 3), (1900, 4), (2300, 5)])
def test_hinge_count_scales_with_height(h, n):
    assert hinge_count(h) == n


def test_doors_get_hinge_cups():
    sched = drilling_schedule(spec(doors=2))
    cup_ops = [op for op in sched.ops if "hinge cup" in op.operation]
    assert len(cup_ops) == 2
    assert all(h.dia == HINGE_CUP_DIA for op in cup_ops for h in op.holes)


def test_doors_get_hinge_mounting_plate_screws():
    sched = drilling_schedule(spec(doors=2))
    plate_ops = [op for op in sched.ops if "hinge plate" in op.operation]
    assert len(plate_ops) == 2, "one plate-screw op per door, on its side"
    # Plate screws land on the cabinet sides, two per hinge.
    assert all(op.part.startswith("Side") for op in plate_ops)


def test_tall_door_gets_more_hinges():
    tall = spec(cabinet_type=CabinetType.TALL, height=2100, doors=2,
                toe_kick=ToeKick(100, 50))
    op = next(o for o in drilling_schedule(tall).ops if "hinge cup" in o.operation)
    assert len(op.holes) >= 4


def test_left_and_right_doors_hinge_opposite_edges():
    sched = drilling_schedule(spec(doors=2, width=800))
    door_l = next(o for o in sched.ops if o.part == "Door L")
    door_r = next(o for o in sched.ops if o.part == "Door R")
    # L hinges near u=0 (left edge), R hinges near its right edge (large u).
    assert door_l.holes[0].u < door_r.holes[0].u


# --- drawer slides -------------------------------------------------------

def test_drawer_slide_lines_present():
    sched = drilling_schedule(spec(doors=0, drawers=[Drawer(140), Drawer(160)]))
    slide_ops = [op for op in sched.ops if "slide line" in op.operation]
    # 2 drawers x 2 sides = 4 slide lines.
    assert len(slide_ops) == 4


# --- output --------------------------------------------------------------

def test_csv_and_report_render():
    sched = drilling_schedule(spec())
    assert sched.total_holes > 0
    assert sched.to_csv().splitlines()[0].startswith("id,part,operation")
    assert "Drilling schedule" in sched.report_text()
