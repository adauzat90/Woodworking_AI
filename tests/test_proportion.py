"""Tests for the PROP-* proportion advisories (INFO severity): golden-ratio
faces, leg slenderness, and drawer-bank graduation."""

from woodworking_ai import (
    CabinetSpec, CabinetType, ToeKick, Drawer, TableSpec, validate, proportion,
)
from woodworking_ai.service import build_result


def base(**o) -> CabinetSpec:
    d = dict(name="B", cabinet_type=CabinetType.BASE, width=600, height=720,
             depth=560, shelves=0, doors=2, toe_kick=ToeKick(100, 50))
    d.update(o)
    return CabinetSpec(**d)


def table(**o) -> TableSpec:
    d = dict(name="T", width=1300, depth=803, height=740, leg=60,
             apron_height=90, top_thickness=25, leg_inset=40)
    d.update(o)
    return TableSpec(**d)


# --- pure helpers --------------------------------------------------------

def test_ratio_is_orientation_independent():
    assert proportion.ratio_of(1600, 1000) == proportion.ratio_of(1000, 1600)
    assert proportion.ratio_of(1000, 1000) == 1.0


def test_golden_detected():
    assert proportion.is_golden(1.618)
    assert not proportion.is_golden(1.9)


def test_nearest_pleasing_picks_closest():
    val, dist = proportion.nearest_pleasing(1.51)
    assert val == 1.5
    assert dist < 0.02


def test_awkward_when_far_from_every_pleasing_ratio():
    assert proportion.is_awkward(1.78)      # between 3:2 and golden and 2:1
    assert not proportion.is_awkward(1.62)  # golden
    assert not proportion.is_awkward(1.0)   # square


def test_golden_targets_round_trip():
    longer, shorter = 1600.0, 1000.0
    tall_target, short_target = proportion.golden_targets(longer, shorter)
    assert proportion.is_golden(tall_target / shorter)
    assert proportion.is_golden(longer / short_target)


def test_graduation_uniform_and_increasing_are_fine():
    assert proportion.is_well_graduated([140, 140, 140])      # uniform
    assert proportion.is_well_graduated([100, 140, 180])      # graduated
    assert not proportion.is_well_graduated([80, 200, 80])    # irregular


# --- cabinet face (PROP-001) ---------------------------------------------

def test_golden_face_no_advisory():
    # box height 618 over 1000 width ≈ 1.618:1.
    spec = base(width=1000, height=718, toe_kick=ToeKick(100, 50))
    assert not any(i.field == "proportion" for i in validate(spec).infos)


def test_awkward_face_gets_advisory():
    spec = base(width=600, height=1150, toe_kick=ToeKick(100, 50))  # box 1050 → 1.75:1
    infos = validate(spec).infos
    assert any(i.field == "proportion" for i in infos)


def test_advisory_does_not_block_build():
    spec = base(width=600, height=1150, toe_kick=ToeKick(100, 50))
    assert validate(spec).ok  # info never affects ok


# --- drawer bank graduation (PROP-003) -----------------------------------

def test_irregular_drawer_bank_advises():
    spec = base(cabinet_type=CabinetType.DRESSER, width=900, height=800,
                depth=500, doors=0, anti_tip=True,
                drawers=[Drawer(80), Drawer(200), Drawer(80)])
    assert any(i.field == "drawers" for i in validate(spec).infos)


def test_graduated_drawer_bank_no_advice():
    spec = base(cabinet_type=CabinetType.DRESSER, width=900, height=900,
                depth=500, doors=0, anti_tip=True,
                drawers=[Drawer(120), Drawer(160), Drawer(200)])
    assert not any(i.field == "drawers" for i in validate(spec).infos)


# --- table top + legs (PROP-001/002) -------------------------------------

def test_golden_table_top_no_advisory():
    assert not any(i.field == "proportion" for i in validate(table()).infos)


def test_awkward_table_top_advises():
    assert any(i.field == "proportion"
               for i in validate(table(width=1400, depth=800)).infos)


def test_spindly_leg_advises():
    assert any(i.field == "leg" for i in validate(table(leg=25)).infos)


def test_chunky_leg_advises():
    assert any(i.field == "leg" for i in validate(table(leg=110)).infos)


def test_balanced_leg_no_advice():
    assert not any(i.field == "leg" for i in validate(table(leg=60)).infos)


# --- API surfaces advisories ---------------------------------------------

def test_build_result_exposes_advisories():
    res = build_result(base(width=600, height=1150, toe_kick=ToeKick(100, 50)),
                       want_png=False, want_glb=False)
    assert "advisories" in res
    assert any(a["field"] == "proportion" for a in res["advisories"])
