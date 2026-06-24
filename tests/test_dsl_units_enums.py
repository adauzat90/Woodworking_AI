"""Imperial-input normalization and the promoted enum fields."""


import pytest

from woodworking_ai import (
    CabinetSpec, TableSpec, Drawer, CornerJoint, DovetailTails, SlideType,
    Grain, TopFixing, Joinery,
)


# --- imperial input -> canonical mm -----------------------------------------

def test_cabinet_inches_convert_to_mm():
    c = CabinetSpec.from_dict({
        "units": "in", "width": 36, "height": 34.5, "depth": 24,
        "material": {"carcass": 0.75, "back": 0.25},
        "toe_kick": {"height": 4, "setback": 3},
        "drawers": [{"front_height": 6, "slide_clearance": 0.5}],
    })
    assert c.width == pytest.approx(914.4)
    assert c.height == pytest.approx(876.3)
    assert c.material.carcass == pytest.approx(19.05)
    assert c.material.back == pytest.approx(6.35)
    assert c.toe_kick.height == pytest.approx(101.6)
    assert c.drawers[0].front_height == pytest.approx(152.4)
    assert c.drawers[0].slide_clearance == pytest.approx(12.7)
    # The field is stamped canonical so everything downstream is mm.
    assert c.units == "mm"


def test_metric_input_is_untouched():
    c = CabinetSpec.from_dict({"width": 600, "height": 720})
    assert c.width == 600 and c.height == 720 and c.units == "mm"


def test_counts_and_loads_not_scaled_by_imperial():
    c = CabinetSpec.from_dict({"units": "in", "width": 36, "shelves": 2,
                               "doors": 2, "shelf_load_kg_per_m": 25})
    assert c.shelves == 2 and c.doors == 2
    assert c.shelf_load_kg_per_m == 25     # a load, not a length


def test_table_inches_convert_to_mm():
    t = TableSpec.from_dict({"units": "in", "width": 60, "depth": 30,
                             "height": 29, "leg": 2.5})
    assert t.width == pytest.approx(1524.0)
    assert t.leg == pytest.approx(63.5)
    assert t.units == "mm"


# --- promoted enums ---------------------------------------------------------

def test_drawer_string_fields_become_enums():
    d = Drawer(corner_joint="BUTT", dovetail_tails="side", slide_type="undermount")
    assert d.corner_joint is CornerJoint.BUTT
    assert d.dovetail_tails is DovetailTails.SIDES      # "side" alias
    assert d.slide_type is SlideType.UNDERMOUNT


def test_drawer_enum_str_is_clean_value():
    # The validator relies on str()/lower() yielding the bare value.
    d = Drawer(corner_joint="dovetail")
    assert str(d.corner_joint) == "dovetail"
    assert f"{d.corner_joint}" == "dovetail"
    assert d.corner_joint == "dovetail"


def test_unknown_drawer_joint_left_as_string_for_validator():
    d = Drawer(corner_joint="welded")
    assert d.corner_joint == "welded"        # not an enum, validator will warn


def test_table_enums_and_aliases():
    t = TableSpec(grain="quarter", top_fixing="fixed", joinery="domino")
    assert t.grain is Grain.QUARTERSAWN
    assert t.top_fixing is TopFixing.FIXED
    assert t.joinery is Joinery.DOMINO


def test_specs_serialize_enums_as_plain_strings():
    c = CabinetSpec(drawers=[Drawer(corner_joint="box")])
    d = c.to_dict()
    assert d["drawers"][0]["corner_joint"] == "box"
    assert isinstance(d["drawers"][0]["corner_joint"], str)
    t = TableSpec(grain="quartersawn").to_dict()
    assert t["grain"] == "quartersawn"


def test_enum_specs_roundtrip():
    c = CabinetSpec.from_dict({"width": 800, "drawers": [
        {"front_height": 150, "corner_joint": "rabbet", "slide_type": "undermount"}]})
    assert CabinetSpec.from_json(c.to_json()).to_dict() == c.to_dict()
