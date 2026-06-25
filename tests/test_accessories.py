"""Typed accessories normalize to the canonical dict; validation flags bad ones."""

from woodworking_ai import (
    CabinetSpec, Countertop, Filler, EndPanel, Molding, validate,
    generate_cutlist,
)


def _cab(accessories, **o):
    d = dict(cabinet_type="base", name="Base", width=900, height=720,
             depth=600, accessories=accessories)
    d.update(o)
    return CabinetSpec(**d)


# --- typed -> dict normalization ----------------------------------------

def test_typed_accessories_normalize_to_dicts_on_construction():
    spec = _cab([Countertop(depth=640, material="butcher_block"),
                 Filler(width=75, side="left"),
                 EndPanel(side="right"),
                 Molding(type="crown", height=90)])
    # Stored as plain dicts, so every consumer reads one shape.
    assert all(isinstance(a, dict) for a in spec.accessories)
    kinds = [a["kind"] for a in spec.accessories]
    assert kinds == ["countertop", "filler", "end_panel", "molding"]


def test_typed_countertop_dict_matches_handwritten():
    typed = _cab([Countertop(depth=640)]).accessories[0]
    assert typed == {"kind": "countertop", "thickness": 38.0,
                     "material": "laminate", "overhang": 25.0, "depth": 640.0}


def test_typed_accessories_produce_the_same_cutlist_as_dicts():
    typed = generate_cutlist(_cab([Countertop(depth=640), Filler(width=75)]))
    loose = generate_cutlist(_cab([{"kind": "countertop", "depth": 640},
                                   {"kind": "filler", "width": 75}]))
    assert {p.name for p in typed.parts} == {p.name for p in loose.parts}


def test_countertop_omits_zero_depth_so_default_applies():
    # depth left at 0 must not serialize as 0 (which would override the default).
    assert "depth" not in Countertop().to_dict()


# --- validation ----------------------------------------------------------

def test_unknown_accessory_kind_warns():
    res = validate(_cab([{"kind": "gadget"}]))
    assert any("unknown accessory kind 'gadget'" in w.message
               for w in res.warnings)


def test_bad_filler_side_warns():
    res = validate(_cab([{"kind": "filler", "width": 75, "side": "lft"}]))
    assert any(w.field == "filler" and "side" in w.message for w in res.warnings)


def test_good_side_does_not_warn():
    res = validate(_cab([Filler(width=75, side="left")]))
    assert not any("side" in w.message for w in res.warnings)


def test_bad_molding_type_warns():
    res = validate(_cab([{"kind": "molding", "type": "egg_and_dart"}]))
    assert any(w.field == "molding" for w in res.warnings)


def test_known_molding_type_ok():
    res = validate(_cab([Molding(type="light_rail", height=40)]))
    assert not any(w.field == "molding" for w in res.warnings)
