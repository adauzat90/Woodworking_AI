"""Pure-math tests for the DSL, validator and cut list.

These run with no CAD dependency and no API key — they exercise the
business-critical core.
"""

import json

import pytest

from woodworking_ai import CabinetSpec, Material, ToeKick, Drawer, validate, generate_cutlist
from woodworking_ai.dsl import BackStyle


def base_spec(**overrides) -> CabinetSpec:
    defaults = dict(
        name="Test", width=600, height=720, depth=560,
        material=Material(carcass=18, back=6, door=18, shelf=18),
        toe_kick=ToeKick(height=100, setback=50),
        shelves=1, doors=2, drawers=[], reveal=3,
    )
    defaults.update(overrides)
    return CabinetSpec(**defaults)


# --- DSL round-trip ------------------------------------------------------

def test_spec_json_roundtrip():
    spec = base_spec(drawers=[Drawer(front_height=140)])
    restored = CabinetSpec.from_json(spec.to_json())
    assert restored.to_dict() == spec.to_dict()


def test_from_dict_ignores_unknown_keys():
    data = json.loads(base_spec().to_json())
    data["future_field"] = "ignored"
    spec = CabinetSpec.from_dict(data)
    assert spec.width == 600


def test_enums_serialize_as_strings():
    d = base_spec().to_dict()
    assert d["construction"] == "frameless"
    assert d["back"] == "rabbeted"


# --- validator -----------------------------------------------------------

def test_valid_cabinet_passes():
    assert validate(base_spec()).ok


@pytest.mark.parametrize("override", [
    dict(width=-1),
    dict(width=0),
    dict(material=Material(carcass=0)),
    dict(doors=3),
    dict(shelves=-2),
    dict(reveal=-1),
])
def test_bad_specs_fail(override):
    assert not validate(base_spec(**override)).ok


def test_toe_kick_taller_than_cabinet_fails():
    spec = base_spec(height=80, toe_kick=ToeKick(height=100, setback=50))
    assert not validate(spec).ok


def test_drawers_taller_than_opening_fails():
    spec = base_spec(drawers=[Drawer(front_height=1000)])
    assert not validate(spec).ok


def test_wide_single_door_warns_but_builds():
    result = validate(base_spec(width=900, doors=1))
    assert result.ok
    assert any(w.field == "doors" for w in result.warnings)


# --- cut list ------------------------------------------------------------

def test_cutlist_has_core_carcass_parts():
    cl = generate_cutlist(base_spec())
    names = {p.name for p in cl.parts}
    assert {"Side", "Bottom", "Top stretcher", "Back", "Toe kick"} <= names


def test_two_sides_are_emitted():
    cl = generate_cutlist(base_spec())
    side = next(p for p in cl.parts if p.name == "Side")
    assert side.qty == 2
    assert side.thickness == 18


def test_bottom_width_accounts_for_two_sides():
    cl = generate_cutlist(base_spec(width=600))
    bottom = next(p for p in cl.parts if p.name == "Bottom")
    # interior width = 600 - 2*18 = 564
    assert bottom.length == pytest.approx(564)


def test_two_doors_split_width_with_reveal():
    cl = generate_cutlist(base_spec(width=600, doors=2, reveal=3))
    door = next(p for p in cl.parts if p.name == "Door")
    assert door.qty == 2
    # (600 - 3*3) / 2 = 295.5
    assert door.width == pytest.approx(295.5)


def test_shelf_hardware_pins_scale():
    cl = generate_cutlist(base_spec(shelves=3))
    pins = next(h for h in cl.hardware if h.name == "Shelf pin")
    assert pins.qty == 12  # 4 per shelf


def test_drawer_generates_slide_and_pull():
    cl = generate_cutlist(base_spec(doors=0, drawers=[Drawer(140), Drawer(180)]))
    slides = [h for h in cl.hardware if h.name == "Drawer slide (pair)"]
    assert sum(h.qty for h in slides) == 2
    fronts = [p for p in cl.parts if p.name.startswith("Drawer front")]
    assert len(fronts) == 2


def test_applied_back_spans_full_width():
    cl = generate_cutlist(base_spec(width=600, back=BackStyle.APPLIED))
    back = next(p for p in cl.parts if p.name == "Back")
    assert max(back.length, back.width) == pytest.approx(720 - 100)  # box height


def test_sheet_area_is_positive():
    assert generate_cutlist(base_spec()).sheet_area_m2 > 0
