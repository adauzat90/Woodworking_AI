"""Buyer-friendly stock labels for internal cut-list material categories."""

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
