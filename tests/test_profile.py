"""Shop profile: standards applied to specs that omit fields; JSON round-trip."""

from woodworking_ai.profile import ShopProfile, profile_from_dict
from woodworking_ai.dsl import spec_from_dict, Construction, Joinery


def test_roundtrip_preserves_overrides():
    p = ShopProfile(name="My Shop", construction="face_frame", joinery="domino",
                    reveal=2.0, carcass_thickness=19.0, hardware_brand="blum")
    p.prices.sheet_price_default = 88.0
    p.sheet.length = 3050.0
    back = profile_from_dict(p.to_dict())
    assert back.construction == "face_frame"
    assert back.joinery == "domino"
    assert back.reveal == 2.0
    assert back.carcass_thickness == 19.0
    assert back.hardware_brand == "blum"
    assert back.prices.sheet_price_default == 88.0
    assert back.sheet.length == 3050.0


def test_defaults_fill_missing_fields_only():
    profile = ShopProfile(construction="face_frame", joinery="pocket", reveal=2.0,
                          carcass_thickness=19.0)
    # A bare cabinet that sets only its size and an explicit joinery.
    raw = {"cabinet_type": "base", "width": 600, "height": 720, "depth": 560,
           "joinery": "dado"}
    filled = profile.apply_defaults(raw)
    spec = spec_from_dict(filled)
    assert spec.construction == Construction.FACE_FRAME   # filled from profile
    assert spec.joinery == Joinery.DADO                   # explicit choice wins
    assert spec.reveal == 2.0                             # filled
    assert spec.material.carcass == 19.0                  # filled


def test_defaults_recurse_into_project_components():
    profile = ShopProfile(construction="face_frame")
    raw = {"kind": "project", "name": "Run", "components": [
        {"spec": {"cabinet_type": "base", "width": 600, "height": 720,
                  "depth": 560}, "x": 0, "y": 0},
    ]}
    filled = profile.apply_defaults(raw)
    group = spec_from_dict(filled)
    assert group.components[0].spec.construction == Construction.FACE_FRAME


def test_apply_defaults_does_not_mutate_input():
    profile = ShopProfile(construction="face_frame")
    raw = {"cabinet_type": "base", "width": 600, "height": 720, "depth": 560}
    profile.apply_defaults(raw)
    assert "construction" not in raw   # original untouched
