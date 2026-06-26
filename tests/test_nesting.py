"""Tests for the sheet-nesting layout used by the web UI's cut diagram."""

from woodworking_ai.dsl import spec_from_dict
from woodworking_ai.estimator import SheetSize, estimate
from woodworking_ai.nesting import nest_layout

BASE = {
    "cabinet_type": "base", "name": "Base", "width": 600, "height": 720,
    "depth": 560, "doors": 2, "shelves": 1,
    "toe_kick": {"height": 100, "setback": 50}, "reveal": 3,
}


def _spec(d):
    return spec_from_dict(d)


def test_nest_layout_returns_placements_per_stock():
    out = nest_layout(_spec(BASE))
    assert out, "expected at least one stock group"
    for g in out:
        assert g["stock"] and g["thickness"] > 0
        assert g["sheet_count"] == len(g["sheets"])
        assert 0.0 <= g["utilization"] <= 1.0
        for sheet in g["sheets"]:
            for r in sheet:
                # Every placed part is a labelled rectangle inside the sheet.
                assert r["w"] > 0 and r["h"] > 0 and r["label"]
                assert r["x"] >= 0 and r["y"] >= 0
                assert r["x"] + r["w"] <= g["sheet_length"] + 1e-6
                assert r["y"] + r["h"] <= g["sheet_width"] + 1e-6


def test_nest_sheet_count_matches_cost_estimate():
    """The diagram must agree with the quote: same total sheet count."""
    spec = _spec(BASE)
    nest = nest_layout(spec)
    est = estimate(spec)
    nest_sheets = sum(g["sheet_count"] for g in nest)
    assert nest_sheets == est.total_sheets


def test_nest_excludes_solid_lumber():
    # A table is solid lumber (top/legs/aprons) — no sheet groups to nest.
    table = _spec({"kind": "table", "name": "T", "width": 1400, "depth": 800,
                   "height": 740})
    assert nest_layout(table) == []


def test_nest_every_part_instance_is_placed():
    spec = _spec(BASE)
    placed = sum(len(s) for g in nest_layout(spec) for s in g["sheets"])
    from woodworking_ai.cutlist import generate_cutlist
    cl = generate_cutlist(spec)
    sheet_parts = sum(p.qty for p in cl.parts if not p.is_solid_lumber)
    assert placed == sheet_parts


def test_nest_smaller_sheet_needs_more_sheets():
    spec = _spec(BASE)
    big = sum(g["sheet_count"] for g in nest_layout(spec))
    small = sum(g["sheet_count"] for g in
                nest_layout(spec, sheet=SheetSize(length=1200, width=600)))
    assert small >= big


def test_combine_sheet_stock_merges_same_thickness():
    """Combining nests same-thickness parts together: fewer or equal sheets."""
    spec = _spec(BASE)
    sep = nest_layout(spec)
    comb = nest_layout(spec, combine_sheet_stock=True)
    # One group per distinct thickness when combined.
    thk = [g["thickness"] for g in comb]
    assert len(thk) == len(set(thk))
    assert sum(g["sheet_count"] for g in comb) <= sum(g["sheet_count"] for g in sep)
    # Every sheet part is still placed.
    from woodworking_ai.cutlist import generate_cutlist
    cl = generate_cutlist(spec)
    sheet_parts = sum(p.qty for p in cl.parts if not p.is_solid_lumber)
    placed = sum(len(s) for g in comb for s in g["sheets"])
    assert placed == sheet_parts


def test_combine_sheet_stock_lowers_or_equals_cost_and_sheets():
    from woodworking_ai.estimator import estimate
    spec = _spec(BASE)
    base = estimate(spec)
    comb = estimate(spec, combine_sheet_stock=True)
    assert comb.total_sheets <= base.total_sheets
    assert comb.material_cost <= base.material_cost
    # Nesting and the quote still agree under combining.
    assert sum(g["sheet_count"] for g in
               nest_layout(spec, combine_sheet_stock=True)) == comb.total_sheets


def test_nest_project_aggregates_components():
    proj = _spec({"kind": "project", "name": "K", "components": [
        {"label": "A", "x": 0, "y": 0,
         "spec": {"cabinet_type": "base", "width": 600, "doors": 2, "shelves": 1}},
        {"label": "B", "x": 600, "y": 0,
         "spec": {"cabinet_type": "base", "width": 600,
                  "drawers": [{"front_height": 160}]}},
    ]})
    out = nest_layout(proj)
    assert out and sum(g["sheet_count"] for g in out) >= 1
