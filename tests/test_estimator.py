"""Tests for the Estimator (nesting + cost). Pure math, no deps."""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, estimate, PriceBook, SheetSize, pack_sheets,
)


def base_spec(**o) -> CabinetSpec:
    d = dict(name="Test", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- nesting -------------------------------------------------------------

def test_two_small_parts_fit_one_sheet():
    sheets, util, oversize = pack_sheets([(600, 400), (600, 400)], SheetSize())
    assert sheets == 1
    assert oversize == 0
    assert 0 < util <= 1


def test_oversize_part_flagged():
    sheets, util, oversize = pack_sheets([(3000, 400)], SheetSize())
    assert oversize == 1


def test_many_parts_need_multiple_sheets():
    rects = [(1200, 1100)] * 6  # each ~ half a sheet height, won't all fit on one
    sheets, util, oversize = pack_sheets(rects, SheetSize())
    assert sheets >= 3


def test_auto_orientation_fits_long_part():
    # 2000 long fits along the 2440 length even though 2000 > 1220 width.
    sheets, util, oversize = pack_sheets([(400, 2000)], SheetSize())
    assert oversize == 0
    assert sheets == 1


def test_utilization_never_exceeds_one():
    for rects in ([(600, 400)], [(1200, 600)] * 10, [(800, 500)] * 3):
        _, util, _ = pack_sheets(rects, SheetSize())
        assert 0 <= util <= 1


# --- estimate ------------------------------------------------------------

def test_estimate_totals_add_up():
    est = estimate(base_spec())
    assert est.total > 0
    assert est.total == pytest.approx(
        est.material_cost + est.hardware_cost
        + est.edge_banding_cost + est.labour_cost
    )


def test_estimate_has_sheet_groups():
    est = estimate(base_spec())
    assert est.groups
    assert est.total_sheets >= 1
    # Carcass, back panel and door/front are distinct material groups.
    materials = {g.material for g in est.groups}
    assert "sheet" in materials and "door/front" in materials


def test_custom_pricebook_changes_cost():
    cheap = PriceBook(shop_rate_per_hour=10.0)
    dear = PriceBook(shop_rate_per_hour=200.0)
    assert estimate(base_spec(), prices=dear).labour_cost > \
        estimate(base_spec(), prices=cheap).labour_cost


def test_more_doors_more_hardware():
    one = estimate(base_spec(doors=1, width=450))
    two = estimate(base_spec(doors=2))
    assert two.hardware_cost > one.hardware_cost


def test_no_edge_banding_zero_cost():
    est = estimate(base_spec(edge_banding=False))
    assert est.edge_banding_cost == 0


def test_tall_cabinet_uses_more_sheets_than_base():
    tall = base_spec(cabinet_type=CabinetType.TALL, height=2100, shelves=5,
                     toe_kick=ToeKick(100, 50))
    assert estimate(tall).total_sheets >= estimate(base_spec()).total_sheets


def test_report_text_renders():
    text = estimate(base_spec()).report_text()
    assert "Cost estimate" in text
    assert "TOTAL" in text


# --- solid lumber priced by the board foot -------------------------------

def test_frameless_cabinet_has_no_lumber_cost():
    """An all-sheet-goods cabinet has zero board feet and zero lumber cost."""
    est = estimate(base_spec())
    assert est.lumber_groups == []
    assert est.lumber_cost == 0
    assert est.total_board_feet == 0
    # Solid materials must not leak into the sheet packing.
    assert all(g.material not in {"frame", "top", "leg", "apron"} for g in est.groups)


def test_face_frame_priced_by_board_foot():
    """Face-frame stock is solid lumber, billed per board foot (incl. waste)."""
    est = estimate(base_spec(construction="face_frame"))
    frame = [g for g in est.lumber_groups if g.material == "frame"]
    assert frame and est.lumber_cost > 0
    g = frame[0]
    prices = PriceBook()
    expect = g.board_feet * prices.lumber_waste_factor * prices.board_foot_price["frame"]
    assert g.cost == pytest.approx(expect)
    assert est.total == pytest.approx(
        est.material_cost + est.lumber_cost + est.hardware_cost
        + est.edge_banding_cost + est.labour_cost)


def test_board_foot_price_changes_lumber_cost():
    base = PriceBook()
    dear = PriceBook(board_foot_price={"frame": base.board_foot_price["frame"] * 2})
    spec = base_spec(construction="face_frame")
    assert estimate(spec, prices=dear).lumber_cost > \
        estimate(spec, prices=base).lumber_cost
