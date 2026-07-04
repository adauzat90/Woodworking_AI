"""Shared sub-components (LeggedBase / ShelfBank) and their use inside a piece.

Covers the components' own compiler rules (positive + negative), the
components-in-piece expansion (panels / cut-list merge, issue prefixing, unknown
name, joinery), and imperial round-tripping.
"""

import pytest

from woodworking_ai import (
    spec_from_dict, validate, generate_cutlist, estimate,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.components import (
    LeggedBase, ShelfBank, available_components, component_from_dict,
    length_fields, is_component,
)
from woodworking_ai.dsl import MM_PER_IN


# ---------------------------------------------------------------------------
# LeggedBase — geometry + its own rules
# ---------------------------------------------------------------------------

def _base(**kw) -> LeggedBase:
    base = dict(width=1200, depth=600, height=740, top_thickness=20, leg=60,
                leg_inset=40, apron_height=90, apron_thickness=20)
    base.update(kw)
    return LeggedBase(**base)


def test_legged_panels_and_cut_parts_counts():
    b = _base(stretchers=True)
    panels = b.panels()
    assert sum(1 for p in panels if p.label.startswith("Leg")) == 4
    assert sum(1 for p in panels if p.category == "apron") == 4
    assert sum(1 for p in panels if p.category == "stretcher") == 2
    names = [p.name for p in b.cut_parts()]
    assert names.count("Leg") == 1        # one aggregated row of qty 4
    assert "Stretcher" in names
    assert _base(stretchers=False).cut_parts()[-1].name != "Stretcher"


def test_legged_panels_translate_to_origin():
    # The default origin is the instance `at`; passing one overrides it.
    b = _base(at=(100, 0, 0))
    leg0 = next(p for p in b.panels() if p.label == "Leg 1")
    leg0_shifted = next(p for p in b.panels(origin=(200, 0, 0)) if p.label == "Leg 1")
    assert leg0_shifted.center[0] - leg0.center[0] == pytest.approx(100)


def test_legged_validate_clean_base_has_no_errors():
    assert not any(i.severity == "error" for i in _base().validate())


def test_legged_validate_rejects_nonpositive():
    assert any(i.severity == "error" and i.field == "width"
               for i in _base(width=0).validate())


def test_legged_validate_bad_leg_depth():
    assert any(i.field == "leg_depth" and i.severity == "error"
               for i in _base(leg_depth=-4).validate())


def test_legged_validate_legs_dont_fit():
    iss = _base(leg_inset=700).validate()
    assert any(i.field == "leg_inset" and i.severity == "error" for i in iss)


def test_legged_validate_too_short():
    iss = _base(height=100, top_thickness=40, apron_height=90).validate()
    assert any(i.field == "height" and i.severity == "error" for i in iss)


def test_legged_validate_surface_noun_in_message():
    from woodworking_ai.components import _LeggedNaming
    b = _base(leg_inset=700)
    object.__setattr__(b, "naming", _LeggedNaming(surface_noun="seat"))
    assert any("seat" in i.message for i in b.validate() if i.field == "leg_inset")


def test_legged_validate_slenderness_spindly_and_heavy():
    spindly = _base(leg=20, height=900).validate()
    assert any(i.rule_id == "PROP-002" and "spindly" in i.message for i in spindly)
    heavy = _base(leg=200, height=900).validate()
    assert any(i.rule_id == "PROP-002" and "heavy" in i.message for i in heavy)


def test_legged_validate_apron_vs_leg():
    iss = _base(leg=60, apron_thickness=60).validate()
    assert any(i.field == "apron_thickness" and i.severity == "warning"
               for i in iss)


def test_legged_validate_stretcher_setback_below_floor():
    iss = _base(stretchers=True, stretcher_setback=5, stretcher_height=40).validate()
    assert any(i.field == "stretcher_setback" for i in iss)


def test_legged_validate_stretcher_into_apron():
    iss = _base(stretchers=True, stretcher_setback=690, stretcher_height=40).validate()
    assert any(i.field == "stretcher_setback" for i in iss)


def test_legged_to_from_dict_roundtrip():
    b = _base(leg_depth=38, stretchers=True, joinery="domino")
    again = LeggedBase.from_dict(b.to_dict())
    assert again.leg_depth == 38 and again.stretchers and again.joinery == "domino"


# ---------------------------------------------------------------------------
# ShelfBank — shelf sag + spacing rules
# ---------------------------------------------------------------------------

def _bank(**kw) -> ShelfBank:
    base = dict(width=900, depth=400, height=1000, shelf_thickness=18,
                upright_thickness=18, shelves=3, load_kg_per_m=30)
    base.update(kw)
    return ShelfBank(**base)


def test_shelfbank_panels_and_parts():
    b = _bank(shelves=4)
    panels = b.panels()
    assert sum(1 for p in panels if p.label.startswith("Upright")) == 2
    assert sum(1 for p in panels if p.label.startswith("Shelf")) == 4
    names = [p.name for p in b.cut_parts()]
    assert names == ["Upright", "Shelf"]
    assert b.cut_parts()[1].qty == 4


def test_shelfbank_clean_bank_ok():
    assert not any(i.severity == "error" for i in _bank().validate())


def test_shelfbank_sag_fails_on_long_thin_heavy_span():
    iss = _bank(width=2000, shelf_thickness=12, load_kg_per_m=80,
                species="pine").validate()
    assert any(i.field == "shelf_thickness" and i.severity in ("error", "warning")
               for i in iss)


def test_shelfbank_spacing_too_tight_warns():
    iss = _bank(height=500, shelves=6).validate()
    assert any(i.field == "shelves" and i.severity == "warning" for i in iss)


def test_shelfbank_uprights_wider_than_bank():
    iss = _bank(width=30, upright_thickness=40).validate()
    assert any(i.field == "width" and i.severity == "error" for i in iss)


def test_shelfbank_spacing_derives_count():
    b = _bank(height=1000, spacing=250, shelves=99)
    assert b.shelf_count == 4       # 1000 // 250


def test_shelfbank_roundtrip():
    b = _bank(species="birch", material_form="plywood")
    again = ShelfBank.from_dict(b.to_dict())
    assert again.species == "birch" and again.material_form == "plywood"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_lists_components():
    assert available_components() == ["legged_base", "shelf_bank"]
    assert is_component("legged_base") and not is_component("nope")
    assert "width" in length_fields("legged_base")


def test_component_from_dict_unknown_raises():
    with pytest.raises(KeyError):
        component_from_dict({"component": "no_such_block"})


# ---------------------------------------------------------------------------
# Components inside a piece — end to end
# ---------------------------------------------------------------------------

def _assembly_table() -> dict:
    return {
        "kind": "piece", "name": "Assembly Table", "units": "mm",
        "material_form": "solid", "species": "spf",
        "parts": [{"name": "Top", "at": [0, 0, 882], "size": [1200, 600, 18],
                   "grain": "x", "material_form": "plywood", "species": "birch"}],
        "components": [
            {"component": "legged_base", "name": "Base", "at": [0, 0, 0],
             "width": 1200, "depth": 600, "height": 900, "top_thickness": 18,
             "leg": 89, "leg_depth": 38, "leg_inset": 40, "apron_height": 89,
             "apron_thickness": 38, "joinery": "mortise_tenon"},
            {"component": "shelf_bank", "name": "Lower shelf", "at": [150, 100, 0],
             "width": 900, "depth": 400, "height": 320, "shelf_thickness": 18,
             "upright_thickness": 18, "shelves": 1, "load_kg_per_m": 40,
             "species": "birch", "material_form": "plywood"},
        ],
    }


def test_piece_with_components_validates_clean():
    spec = spec_from_dict(_assembly_table())
    from woodworking_ai import PieceSpec
    assert isinstance(spec, PieceSpec)
    r = validate(spec)
    assert r.ok and not r.issues


def test_piece_components_expand_panels():
    spec = spec_from_dict(_assembly_table())
    labels = [p.label for p in panel_layout(spec)]
    # 1 top + (4 legs + 4 aprons) + (2 uprights + 1 shelf) = 12
    assert len(labels) == 12
    assert "Base Leg 1" in labels and "Lower shelf Shelf 1" in labels


def test_piece_components_merge_cutlist_with_prefixed_ids():
    cl = generate_cutlist(spec_from_dict(_assembly_table()))
    names = [p.name for p in cl.parts]
    assert "Base Leg" in names and "Lower shelf Shelf" in names
    assert all(p.id for p in cl.parts)          # every merged part gets an ID
    # the legs price as solid SPF sticks, not sheet goods
    leg = next(p for p in cl.parts if p.name == "Base Leg")
    assert leg.is_solid_lumber and leg.species == "spf"


def test_piece_components_merge_joinery():
    ops = [o.operation for o in joinery_schedule(spec_from_dict(_assembly_table())).ops]
    assert "leg-to-apron joint" in ops and "shelf-to-upright housing" in ops


def test_piece_component_validate_issues_are_prefixed():
    d = _assembly_table()
    d["components"][0]["leg_inset"] = 700       # legs no longer fit the base
    r = validate(spec_from_dict(d))
    assert not r.ok
    assert any(i.field.startswith("Base.") and "Base:" in i.message
               for i in r.errors)


def test_piece_unknown_component_is_repairable_error():
    d = _assembly_table()
    d["components"][1]["component"] = "mystery_block"
    r = validate(spec_from_dict(d))
    assert not r.ok
    assert any(i.field == "components" and "mystery_block" in i.message
               for i in r.errors)


def test_piece_components_participate_in_overlap_physics():
    d = _assembly_table()
    # Drop the shelf bank on top of the legs so its parts collide with the base.
    d["components"][1]["at"] = [150, 100, 500]
    d["components"][1]["width"] = 1000
    r = validate(spec_from_dict(d))
    assert any("overlap" in i.message.lower() for i in r.issues)


def test_piece_with_components_imperial_roundtrip():
    imp = {
        "kind": "piece", "name": "Imperial", "units": "in",
        "parts": [{"name": "Top", "at": [0, 0, 34], "size": [48, 24, 0.75]}],
        "components": [
            {"component": "legged_base", "name": "Base", "at": [0, 0, 0],
             "width": 48, "depth": 24, "height": 35, "top_thickness": 0.75,
             "leg": 3.5, "leg_inset": 1.5, "apron_height": 3.5,
             "apron_thickness": 1.5},
        ],
    }
    spec = spec_from_dict(imp)
    assert spec.units == "mm"
    base = spec.components[0]
    assert base.params["width"] == pytest.approx(48 * MM_PER_IN)
    assert base.params["leg"] == pytest.approx(3.5 * MM_PER_IN)
    # round-trips back out through to_dict without a second conversion
    again = spec_from_dict(spec.to_dict())
    assert again.components[0].params["width"] == pytest.approx(48 * MM_PER_IN)
    assert estimate(spec).total > 0
