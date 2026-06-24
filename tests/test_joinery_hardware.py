"""Tests for the joinery, drawer-slide hardware, and real-stock checks
(STRUCT-002/010, STRUCT-011, HW-001/002, GRAIN-001, MAT-001/002/003)."""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer, TableSpec, Joinery,
    validate, stock,
)


def base(**o) -> CabinetSpec:
    d = dict(name="B", cabinet_type=CabinetType.BASE, width=600, height=720,
             depth=560, shelves=0, doors=0, toe_kick=ToeKick(100, 50))
    d.update(o)
    return CabinetSpec(**d)


def table(**o) -> TableSpec:
    d = dict(name="T", width=1400, depth=800, height=740, leg=60,
             apron_height=90, top_thickness=25, leg_inset=40)
    d.update(o)
    return TableSpec(**d)


# --- stock catalog (pure) ------------------------------------------------

def test_standard_sheet_thickness_recognised():
    assert stock.is_standard_sheet_thickness(18.0)
    assert stock.is_standard_sheet_thickness(12.0)
    assert not stock.is_standard_sheet_thickness(16.5)  # between 15 and 18


def test_nearest_sheet_thickness():
    assert stock.nearest_sheet_thickness(19.0) == 18.0
    assert stock.nearest_sheet_thickness(7.0) == 6.0


def test_fits_standard_sheet_orientation_independent():
    assert stock.fits_standard_sheet(2400, 1200)
    assert stock.fits_standard_sheet(1200, 2400)   # rotated
    assert not stock.fits_standard_sheet(2500, 1200)


def test_required_quarter_picks_smallest_yield():
    assert stock.required_quarter(20.0)[0] == "4/4"
    assert stock.required_quarter(25.0)[0] == "5/4"
    assert stock.required_quarter(45.0)[0] == "8/4"
    assert stock.required_quarter(200.0) is None


# --- drawer corner joinery (STRUCT-011 / GRAIN-001) ----------------------

def test_dovetail_drawer_corner_ok():
    spec = base(drawers=[Drawer(160, corner_joint="dovetail")])
    assert not any("drawer" in w.field for w in validate(spec).warnings)


def test_butt_drawer_corner_warns():
    spec = base(drawers=[Drawer(160, corner_joint="butt")])
    msgs = [w.message for w in validate(spec).warnings if w.field == "drawers"]
    assert any("butt" in m for m in msgs)


def test_weak_drawer_corner_warns_once_when_shared():
    """Five identical weak-jointed drawers should warn once, not five times."""
    spec = base(drawers=[Drawer(120, corner_joint="dowel") for _ in range(5)])
    corner_warnings = [w for w in validate(spec).warnings
                       if w.field == "drawers" and "corner" in w.message]
    assert len(corner_warnings) == 1


# --- drawer slide clearance + length (HW-001 / HW-002) -------------------

def test_bad_slide_clearance_warns():
    spec = base(drawers=[Drawer(160, slide_clearance=5.0)])
    assert any("per side" in w.message for w in validate(spec).warnings)


def test_standard_slide_clearance_ok():
    spec = base(drawers=[Drawer(160, slide_clearance=12.7)])
    assert not any("per side" in w.message for w in validate(spec).warnings)


def test_narrow_opening_for_slides_errors():
    # A 60mm-wide cabinet can't host slides + a usable box.
    spec = base(width=60, drawers=[Drawer(160)])
    assert not validate(spec).ok


def test_slide_longer_than_depth_errors():
    spec = base(depth=400, drawers=[Drawer(160, slide_length=700)])
    r = validate(spec)
    assert not r.ok
    assert any("slide length" in e.message for e in r.errors)


def test_slide_fitting_depth_ok():
    spec = base(depth=560, drawers=[Drawer(160, slide_length=500)])
    assert validate(spec).ok


# --- carcass joinery (STRUCT-010) ----------------------------------------

def test_butt_carcass_joinery_warns():
    assert any(w.field == "joinery"
               for w in validate(base(joinery=Joinery.BUTT)).warnings)


def test_dado_carcass_joinery_ok():
    assert not any(w.field == "joinery"
                   for w in validate(base(joinery=Joinery.DADO)).warnings)


# --- table leg-to-apron racking (STRUCT-002) -----------------------------

def test_pocket_screw_leg_apron_warns_racking():
    assert any(w.field == "joinery"
               for w in validate(table(joinery="pocket")).warnings)


def test_mortise_tenon_leg_apron_ok():
    assert not any(w.field == "joinery"
                   for w in validate(table(joinery="mortise_tenon")).warnings)


# --- buildable from real stock (MAT-001/002/003) -------------------------

def test_nonstandard_sheet_thickness_warns():
    spec = base(material=Material(carcass=16.5))  # between 15 and 18mm stock
    assert any(w.field == "material.carcass" for w in validate(spec).warnings)


def test_oversize_panel_warns():
    # A 2700mm-tall pantry side panel won't yield from a 2440mm sheet.
    spec = base(cabinet_type=CabinetType.TALL, height=2700, depth=580,
                shelves=2, doors=2, toe_kick=ToeKick(100, 50), anti_tip=True)
    assert any("standard 2440" in w.message for w in validate(spec).warnings)


def test_thick_solid_top_warns():
    assert any(w.field == "top_thickness"
               for w in validate(table(top_thickness=90, solid_top=True)).warnings)


def test_normal_solid_top_ok():
    assert not any(w.field == "top_thickness"
                   for w in validate(table(top_thickness=25)).warnings)


# --- serialization round-trips with the new fields -----------------------

def test_drawer_new_fields_roundtrip():
    spec = base(drawers=[Drawer(160, corner_joint="box", slide_clearance=12.7,
                                slide_length=500)])
    restored = CabinetSpec.from_json(spec.to_json())
    assert restored.drawers[0].corner_joint == "box"
    assert restored.drawers[0].slide_length == 500


def test_table_joinery_roundtrip():
    t = table(joinery="domino")
    assert TableSpec.from_json(t.to_json()).joinery == "domino"
