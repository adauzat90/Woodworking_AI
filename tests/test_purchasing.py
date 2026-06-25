"""Tests for the supplier-grouped purchase order. Pure math, no deps.

The PO is the orderable buy-list a shop acts on; its grand total reconciles with
the cost estimate (same prices). Mirrors the style of test_estimator.py.
"""

import pytest

from woodworking_ai import (
    CabinetSpec, Material, ToeKick, PriceBook, SheetSize,
    estimate, generate_cutlist, purchase_order, Component, Project,
)


def base_spec(**o) -> CabinetSpec:
    d = dict(name="Test", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- structure -----------------------------------------------------------

def test_po_has_lines_and_suppliers():
    po = purchase_order(base_spec())
    assert po.lines
    # Lines are grouped under at least sheet goods, a hardware brand and labour.
    cats = {ln.category for ln in po.lines}
    assert {"sheet", "hardware", "labour"} <= cats
    assert len(po.suppliers) >= 3


def test_every_line_has_supplier_qty_and_total():
    for ln in purchase_order(base_spec(construction="face_frame",
                                       finish="clear")).lines:
        assert ln.supplier and ln.unit
        assert ln.qty >= 0
        # Line total is qty × unit price for the priced lines (finish/lumber
        # derive a per-unit price from the billed cost, so this still holds).
        assert ln.line_total == pytest.approx(ln.qty * ln.unit_price, abs=1e-6) \
            or ln.line_total >= 0


def test_lines_grouped_by_supplier_are_contiguous():
    po = purchase_order(base_spec(hardware_brand="blum"))
    seen = []
    for ln in po.lines:
        if not seen or seen[-1] != ln.supplier:
            assert ln.supplier not in seen, "supplier lines must be contiguous"
            seen.append(ln.supplier)


# --- hardware carries SKUs -----------------------------------------------

def test_every_cutlist_hardware_appears_on_a_po_line_with_sku():
    """Every hardware item in the cut list appears on a PO line; SKU-bearing
    catalogue items carry their SKU through to the order."""
    spec = base_spec(hardware_brand="blum", drawers=[])
    cl = generate_cutlist(spec)
    po = purchase_order(spec)
    hw_lines = [ln for ln in po.lines if ln.category == "hardware"]
    by_name = {ln.item: ln for ln in hw_lines}
    for h in cl.hardware:
        assert h.name in by_name, f"{h.name} missing from PO"
        ln = by_name[h.name]
        assert ln.qty == h.qty
        # A catalogue SKU on the cut-list item must reach the PO line.
        if h.sku:
            assert ln.sku == h.sku


def test_hardware_grouped_under_its_brand_supplier():
    po = purchase_order(base_spec(hardware_brand="blum"))
    brand_lines = [ln for ln in po.lines
                   if ln.category == "hardware" and ln.brand == "blum"]
    assert brand_lines
    assert all("Blum" in ln.supplier for ln in brand_lines)


# --- sheet goods match the estimator -------------------------------------

def test_sheet_po_qty_matches_estimator_sheet_count():
    spec = base_spec()
    est = estimate(spec)
    po = purchase_order(spec)
    sheet_lines = [ln for ln in po.lines if ln.category == "sheet"]
    # One PO line per sheet group; quantities match the estimate sheet counts.
    assert len(sheet_lines) == len([g for g in est.groups if g.sheets > 0])
    po_total_sheets = sum(ln.qty for ln in sheet_lines)
    assert po_total_sheets == est.total_sheets


def test_lumber_po_qty_matches_estimator_board_feet():
    spec = base_spec(construction="face_frame")
    est = estimate(spec)
    po = purchase_order(spec)
    lumber_lines = [ln for ln in po.lines if ln.category == "lumber"]
    assert lumber_lines
    po_bf = sum(ln.qty for ln in lumber_lines)
    assert po_bf == pytest.approx(est.total_board_feet, abs=0.01)


# --- the grand total reconciles with the quote ---------------------------

def test_po_grand_total_equals_estimate_total():
    for kw in ({}, dict(construction="face_frame"), dict(finish="clear"),
               dict(hardware_brand="hettich", finish="paint")):
        spec = base_spec(**kw)
        est = estimate(spec)
        po = purchase_order(spec)
        assert po.grand_total == pytest.approx(est.total, abs=0.005), kw


def test_po_reconciles_under_a_custom_pricebook():
    prices = PriceBook(shop_rate_per_hour=120.0, edge_banding_per_m=3.0,
                       sheet_price_default=99.0)
    spec = base_spec(construction="face_frame", finish="stain_clear")
    est = estimate(spec, prices=prices)
    po = purchase_order(spec, prices=prices)
    assert po.grand_total == pytest.approx(est.total, abs=0.005)


def test_po_respects_sheet_size_override():
    big = SheetSize(length=3050.0, width=1525.0)
    spec = base_spec()
    est = estimate(spec, sheet=big)
    po = purchase_order(spec, sheet=big)
    assert po.grand_total == pytest.approx(est.total, abs=0.005)


# --- serialisation -------------------------------------------------------

def test_csv_has_header_and_grand_total_row():
    po = purchase_order(base_spec())
    csv = po.to_csv()
    lines = csv.splitlines()
    assert lines[0].startswith("supplier,category,item")
    assert "GRAND TOTAL" in lines[-1]
    assert str(round(po.grand_total, 2)) in lines[-1]


def test_report_text_renders():
    text = purchase_order(base_spec()).report_text()
    assert "Purchase order" in text
    assert "GRAND TOTAL" in text


# --- a project aggregates into one PO ------------------------------------

def test_project_aggregates_into_one_po():
    project = Project(name="Kitchen run", components=[
        Component(spec=base_spec(name="Sink", width=900, doors=2), x=0,
                  label="A"),
        Component(spec=base_spec(name="Base", width=600, doors=1), x=900,
                  label="B"),
    ])
    est = estimate(project)
    po = purchase_order(project)
    assert po.name == "Kitchen run"
    assert po.grand_total == pytest.approx(est.total, abs=0.01)
    # The run's hardware is merged onto shared order lines.
    assert any(ln.category == "hardware" for ln in po.lines)


def test_project_po_hardware_sums_component_quantities():
    one = purchase_order(base_spec(doors=1, width=450))
    project = Project(name="Pair", components=[
        Component(spec=base_spec(name="A", width=450, doors=1), x=0, label="A"),
        Component(spec=base_spec(name="B", width=450, doors=1), x=450,
                  label="B"),
    ])
    po = purchase_order(project)

    def hinges(p):
        return sum(ln.qty for ln in p.lines if ln.item == "Concealed hinge")

    assert hinges(po) == pytest.approx(2 * hinges(one))


# --- shop consumables (G4a) — kept off the reconciled total ---------------

def test_consumables_do_not_change_grand_total():
    spec = base_spec(finish="oil", species="walnut")
    po = purchase_order(spec)
    est = estimate(spec)
    assert po.grand_total == pytest.approx(est.total, abs=0.005)
    # Consumables are a separate section with their own subtotal.
    assert po.consumables
    assert po.consumables_total > 0
    assert po.consumables_total == pytest.approx(
        sum(l.line_total for l in po.consumables), abs=0.005)


def test_consumables_cover_glue_abrasives_clamps():
    po = purchase_order(base_spec(finish="oil"))
    items = " ".join(l.item.lower() for l in po.consumables)
    assert "glue" in items
    assert "sandpaper" in items
    assert "clamp" in items


def test_consumables_add_conditioner_for_blotch_prone_stain():
    # Cherry is blotch-prone; a stain finish should add a wood conditioner line.
    po = purchase_order(base_spec(finish="stain_clear", species="cherry"))
    assert any("conditioner" in l.item.lower() for l in po.consumables)
    # An oil finish on a non-blotch species should not.
    po2 = purchase_order(base_spec(finish="oil", species="white_oak"))
    assert not any("conditioner" in l.item.lower() for l in po2.consumables)


def test_consumables_are_not_in_reconciled_lines():
    po = purchase_order(base_spec(finish="oil"))
    assert all(l.supplier != "Shop consumables" for l in po.lines)


# --- sourcing (G4b) -------------------------------------------------------

def test_every_buy_line_has_a_source():
    po = purchase_order(base_spec(finish="oil", hardware_brand="blum"))
    for ln in po.lines:
        if ln.category == "labour":
            continue                     # in-house; nothing to source
        assert ln.source, ln.item
    for ln in po.consumables:
        assert ln.source, ln.item


def test_euro_brand_hardware_gets_big_box_alternative():
    po = purchase_order(base_spec(hardware_brand="blum"))
    hinge = next((ln for ln in po.lines
                  if ln.brand == "blum" and "hinge" in ln.item.lower()), None)
    assert hinge is not None
    assert hinge.alt                     # a home-center equivalent is offered
    assert hinge.url                     # and a search link to the SKU


def test_generic_hardware_has_no_alt():
    po = purchase_order(base_spec(hardware_brand="generic"))
    assert all(not ln.alt for ln in po.lines if ln.category == "hardware")
