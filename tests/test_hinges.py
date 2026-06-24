"""Tests for HW-005: a 35mm concealed hinge cup must fit the door it's bored
into — enough thickness for the cup depth and enough width for its footprint."""

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, validate,
)
from woodworking_ai import validator as V


def cab(**o) -> CabinetSpec:
    d = dict(name="C", cabinet_type=CabinetType.BASE, width=600, height=720,
             depth=560, shelves=0, doors=2, toe_kick=ToeKick(100, 50))
    d.update(o)
    return CabinetSpec(**d)


def _door_errors(spec):
    return [e for e in validate(spec).errors if e.field in ("doors", "material.door")]


def _door_warnings(spec):
    return [w for w in validate(spec).warnings if w.field in ("doors", "material.door")]


# --- door thickness vs. cup depth ----------------------------------------

def test_min_door_width_constant():
    assert V.HINGE_MIN_DOOR_WIDTH == 40.0  # 22.5 inset + 17.5 cup radius


def test_door_thinner_than_cup_depth_errors():
    spec = cab(material=Material(door=12.0))  # < 12.5mm cup depth
    assert any(e.field == "material.door" for e in _door_errors(spec))


def test_marginal_door_thickness_warns():
    spec = cab(material=Material(door=14.0))  # hosts the cup but little backing
    assert any(w.field == "material.door" for w in _door_warnings(spec))
    assert validate(spec).ok  # a warning, not a hard failure


def test_standard_door_thickness_ok():
    spec = cab(material=Material(door=18.0))
    assert not any(i.field == "material.door" for i in validate(spec).issues)


# --- door width vs. cup footprint ----------------------------------------

def test_two_doors_too_narrow_for_cup_errors():
    # ~39mm doors after splitting an 88mm opening — below the 40mm cup footprint.
    spec = cab(width=88, doors=2)
    errs = _door_errors(spec)
    assert any("hinge cup" in e.message for e in errs)
    assert not validate(spec).ok


def test_two_doors_tight_for_cup_warns():
    spec = cab(width=100, doors=2)  # ~45mm doors — fits but tight
    assert any(w.field == "doors" and "hinge cup" in w.message
               for w in _door_warnings(spec))
    assert validate(spec).ok


def test_normal_doors_have_room_for_hinges():
    spec = cab(width=600, doors=2)  # ~295mm doors
    assert not any("hinge cup" in i.message for i in validate(spec).issues)


def test_single_wide_door_ok():
    spec = cab(width=450, doors=1)
    assert not any("hinge cup" in i.message for i in validate(spec).issues)


# --- scope ---------------------------------------------------------------

def test_doorless_cabinet_skips_hinge_checks():
    spec = cab(doors=0, material=Material(door=10.0))  # thin door, but no doors
    assert not any(i.field == "material.door" for i in validate(spec).issues)


def test_corner_cabinet_skips_door_width_check():
    # An angled/blind corner door isn't a simple rectangle — no width error.
    spec = cab(cabinet_type=CabinetType.CORNER_DIAGONAL, width=600, depth=600,
               corner_cut=450, doors=0)
    assert not any(e.field == "doors" and "hinge cup" in e.message
                   for e in validate(spec).errors)
