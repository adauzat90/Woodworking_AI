"""Sourcing map for the purchase order (sources.source_for).

Pure data + string formatting (no CAD, no network), but was previously only
reached transitively through purchasing. These exercise it directly.
"""

from woodworking_ai import sources
from woodworking_ai.sources import (
    source_for, RETAILER_HARDWARE_DEALER, RETAILER_WOODWORKING,
    RETAILER_HARDWOOD_DEALER, RETAILER_FINISH, RETAILER_SHEET_GOODS,
    RETAILER_HOME_CENTER,
)


def test_euro_brand_hardware_gets_dealer_and_big_box_alt():
    retailer, url, alt = source_for("hardware", brand="Blum",
                                    item="Concealed hinge", sku="71B3550")
    assert retailer == RETAILER_HARDWARE_DEALER
    assert "duckduckgo.com" in url and "71B3550" in url
    assert "hinge" in alt.lower()           # a buy-instead substitute is offered


def test_euro_slide_alt_is_a_slide():
    _, _, alt = source_for("hardware", brand="hettich", item="Drawer slide pair")
    assert "slide" in alt.lower()


def test_generic_hardware_has_no_alt():
    retailer, url, alt = source_for("hardware", brand="generic",
                                    item="Shelf pin", sku="SP5")
    assert retailer == RETAILER_WOODWORKING
    assert alt == ""                         # off-the-shelf already → no substitute
    assert "Shelf+pin" in url or "Shelf%20pin" in url


def test_euro_brand_non_hinge_non_slide_gets_generic_alt():
    # A Euro-brand item that is neither a hinge nor a slide falls back to the
    # generic "buy a home-center equivalent" substitute.
    _, _, alt = source_for("hardware", brand="grass", item="Lift-up stay")
    assert alt == sources._BIG_BOX_ALT["default"]


def test_category_retailers():
    assert source_for("lumber", item="oak")[0] == RETAILER_HARDWOOD_DEALER
    assert source_for("finish", item="poly")[0] == RETAILER_FINISH
    assert source_for("sheet", item="ply")[0] == RETAILER_SHEET_GOODS


def test_unknown_category_falls_back_to_home_center():
    retailer, url, alt = source_for("mystery", item="thing")
    assert retailer == RETAILER_HOME_CENTER
    assert alt == ""


def test_labour_sources_nothing():
    # In-house labour: no retailer, no link, no substitute.
    assert source_for("labour", item="assembly") == ("", "", "")


def test_search_url_is_blank_for_no_terms():
    assert sources._search_url("", "") == ""
    assert sources._search_url("walnut", "board") .startswith("https://duckduckgo.com/?q=")
