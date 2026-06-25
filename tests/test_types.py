"""Tests for wall and tall cabinet types (no CAD / API key)."""


import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, TableSpec, ToeKick, Drawer,
    validate, generate_cutlist, spec_from_dict,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique


# --- the `kind` discriminator -------------------------------------------

def test_explicit_cabinet_kind_routes_to_cabinet():
    spec = spec_from_dict({"kind": "cabinet", "width": 600, "leg": 999})
    # Explicit kind wins over the table-shape heuristic ("leg" present).
    assert isinstance(spec, CabinetSpec)


def test_no_kind_cabinet_still_loads():
    assert isinstance(spec_from_dict({"cabinet_type": "base", "width": 600}),
                      CabinetSpec)


def test_no_kind_table_shape_still_infers_table():
    assert isinstance(spec_from_dict({"width": 1600, "leg": 70}), TableSpec)


def test_unknown_kind_is_rejected_with_helpful_message():
    with pytest.raises(ValueError) as exc:
        spec_from_dict({"kind": "wardrobe", "width": 600})
    msg = str(exc.value)
    assert "wardrobe" in msg and "cabinet" in msg and "table" in msg


def wall(**o) -> CabinetSpec:
    d = dict(name="Wall", cabinet_type=CabinetType.WALL, width=600, height=720,
             depth=350, toe_kick=None, shelves=2, doors=2, reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def tall(**o) -> CabinetSpec:
    d = dict(name="Pantry", cabinet_type=CabinetType.TALL, width=600, height=2100,
             depth=580, toe_kick=ToeKick(100, 50), shelves=5, doors=2, reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- serialization -------------------------------------------------------

def test_cabinet_type_roundtrips():
    spec = wall()
    restored = CabinetSpec.from_json(spec.to_json())
    assert restored.cabinet_type == CabinetType.WALL


def test_legacy_type_string_is_mapped():
    spec = CabinetSpec.from_dict({"type": "wall_cabinet", "width": 600})
    assert spec.cabinet_type == CabinetType.WALL
    spec = CabinetSpec.from_dict({"type": "pantry", "width": 600})
    assert spec.cabinet_type == CabinetType.TALL


# --- full top vs stretchers ---------------------------------------------

def test_wall_and_tall_have_full_top_panel():
    for spec in (wall(), tall()):
        labels = {p.label for p in panel_layout(spec)}
        assert "Top" in labels
        assert "Stretcher front" not in labels


def test_base_keeps_stretchers():
    base = CabinetSpec(name="Base")  # default type BASE
    labels = {p.label for p in panel_layout(base)}
    assert "Stretcher front" in labels
    assert "Top" not in labels


def test_cutlist_top_panel_for_wall():
    cl = generate_cutlist(wall())
    names = {p.name for p in cl.parts}
    assert "Top" in names and "Top stretcher" not in names


def test_wall_has_no_toe_kick_part():
    cl = generate_cutlist(wall())
    assert "Toe kick" not in {p.name for p in cl.parts}


# --- geometry soundness via the critic ----------------------------------

def test_wall_and_tall_pass_critic_without_interference():
    for spec in (wall(), tall(), wall(doors=1, width=400),
                 tall(drawers=[Drawer(150), Drawer(150)], doors=1)):
        crit = critique(spec)
        assert crit.report["interference_count"] == 0, spec.name
        assert abs(crit.report["height"] - spec.height) < 0.5


# --- per-type validation warnings ---------------------------------------

def test_wall_with_toe_kick_warns():
    result = validate(wall(toe_kick=ToeKick(100, 50)))
    assert result.ok
    assert any(w.field == "toe_kick" for w in result.warnings)


def test_tall_without_toe_kick_warns():
    result = validate(tall(toe_kick=None))
    assert any(w.field == "toe_kick" for w in result.warnings)


def test_short_tall_cabinet_warns():
    assert any(w.field == "height" for w in validate(tall(height=1200)).warnings)


# --- bookcase + dresser --------------------------------------------------

def test_bookcase_is_open_with_full_top():
    bc = CabinetSpec(name="BC", cabinet_type=CabinetType.BOOKCASE, width=800,
                     height=1800, depth=300, shelves=4, doors=0,
                     toe_kick=ToeKick(80, 40))
    assert bc.has_full_top
    assert validate(bc).ok
    assert critique(bc).report["interference_count"] == 0
    assert "Top" in {p.label for p in panel_layout(bc)}


def test_bookcase_with_doors_warns():
    bc = CabinetSpec(name="BC", cabinet_type=CabinetType.BOOKCASE, width=800,
                     height=1800, depth=300, shelves=4, doors=2,
                     toe_kick=ToeKick(80, 40))
    assert any(w.field == "doors" for w in validate(bc).warnings)


def test_dresser_drawer_bank():
    dr = CabinetSpec(name="DR", cabinet_type=CabinetType.DRESSER, width=900,
                     height=800, depth=500, shelves=0, doors=0,
                     drawers=[Drawer(180), Drawer(180), Drawer(180)],
                     toe_kick=ToeKick(80, 40))
    assert validate(dr).ok
    assert critique(dr).report["interference_count"] == 0
    fronts = [p for p in generate_cutlist(dr).parts if p.name.startswith("Drawer front")]
    assert len(fronts) == 3


def test_dresser_without_drawers_warns():
    dr = CabinetSpec(name="DR", cabinet_type=CabinetType.DRESSER, width=900,
                     height=800, depth=500, doors=0, drawers=[])
    assert any(w.field == "drawers" for w in validate(dr).warnings)
