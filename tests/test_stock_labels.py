"""Buyer-friendly stock labels for internal cut-list material categories."""

import pytest

from woodworking_ai.stock import stock_label, stock_product


def test_internal_labels_map_to_buyable_stock():
    # The confusing internal usage labels become real "stock to buy" names.
    assert stock_label("drawer box") == "Drawer-box sheet"
    assert stock_label("door panel") == "Door centre-panel stock"
    assert stock_label("back panel").startswith("Back")
    assert stock_label("sheet") == "Carcass sheet"
    assert stock_label("countertop") == "Countertop slab"


def test_typical_product_is_given():
    assert "plywood" in stock_product("sheet").lower()
    assert stock_product("drawer box")          # non-empty


def test_unknown_material_falls_back_to_titlecase():
    assert stock_label("mystery") == "Mystery"
    assert stock_product("mystery") == ""


# --- C3: real stock thickness drives joinery --------------------------------

def test_actual_sheet_thickness_maps_nominal_imperial():
    from woodworking_ai.stock import actual_sheet_thickness
    # Nominal 3/4" plywood machines to ~18.3mm, not a clean 18.0.
    assert actual_sheet_thickness(18.3) == pytest.approx(18.3)
    # A value with no nominal match comes back as-is (already actual).
    assert actual_sheet_thickness(14.0) == pytest.approx(14.0)


def test_joinery_width_tracks_profile_actual_thickness():
    from woodworking_ai.profile import ShopProfile
    from woodworking_ai.dsl import CabinetSpec
    from woodworking_ai.joinery import joinery_schedule
    prof = ShopProfile(carcass_thickness=18.0, carcass_thickness_actual=18.3)
    data = prof.apply_defaults(
        dict(name="B", width=600, height=720, depth=560, joinery="dado"))
    assert data["material"]["carcass"] == pytest.approx(18.3)
    spec = CabinetSpec.from_dict(data)
    dado = next(o for o in joinery_schedule(spec).ops
                if "bottom" in o.operation)
    # The dado is cut to the actual mating-panel thickness, not the nominal.
    assert dado.width == pytest.approx(18.3)


def test_profile_actual_thickness_round_trips():
    from woodworking_ai.profile import ShopProfile, profile_from_dict
    prof = ShopProfile(carcass_thickness_actual=18.3)
    assert profile_from_dict(prof.to_dict()).carcass_thickness_actual == \
        pytest.approx(18.3)
