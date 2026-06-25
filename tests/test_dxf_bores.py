"""Tests for drilling bores emitted into the nested DXF cut-layout (A1).

The nest DXF carries each panel's drilled holes on a ``BORE`` layer, mapped from
the drilling schedule's local (u, v) into the panel's placed rectangle. These
tests pin the high-value cases: door hinge cups (⌀35) and side shelf-pin rows
(⌀5), the total bore count, and that every bore lands inside its part outline.
"""

import re

from woodworking_ai import CabinetSpec, CabinetType, Material, ToeKick, Drawer
from woodworking_ai.dxf import (
    export_cutlayout_dxf, _cutlist_items, _placement_part, _LAYERS,
)
from woodworking_ai.drilling import (
    drilling_schedule, holes_by_part_id, ops_for_instance, place_holes,
)
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.estimator import SheetSize
from woodworking_ai.packing import pack


def spec(**o) -> CabinetSpec:
    d = dict(name="Bore", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def _circles(text: str) -> list[tuple[float, float, float]]:
    """Parse every CIRCLE entity in a DXF as ``(cx, cy, radius)``."""
    out = []
    for m in re.finditer(
            r"\nCIRCLE\n8\n\w+\n10\n([-\d.]+)\n20\n([-\d.]+)\n30\n[-\d.]+\n"
            r"40\n([-\d.]+)", text):
        out.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return out


# --- layers --------------------------------------------------------------

def test_dxf_declares_machining_layers(tmp_path):
    text = export_cutlayout_dxf(spec(), tmp_path / "l.dxf").read_text()
    assert "TABLES" in text and "LAYER" in text
    for layer in ("BORE", "DADO", "RABBET", "CUTOUT"):
        assert layer in _LAYERS
        assert f"\n2\n{layer}\n" in text   # the layer is declared in the table


# --- B2: sink/cooktop cut-out drawn on the CUTOUT layer ------------------

def _cutout_lines(text: str) -> int:
    """Count LINE entities on the CUTOUT layer."""
    return len(re.findall(r"\nLINE\n8\nCUTOUT\n", text))


def test_countertop_cutout_polyline_on_cutout_layer(tmp_path):
    s = spec(width=900, accessories=[
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30},
        {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450}])
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    # One rectangle = four LINE segments, all on the CUTOUT layer.
    assert _cutout_lines(text) == 4


def test_no_cutout_layer_geometry_without_a_sink(tmp_path):
    s = spec(width=900, accessories=[
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30}])
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    assert _cutout_lines(text) == 0


# --- hinge cups on doors -------------------------------------------------

def test_door_hinge_cups_drawn(tmp_path):
    s = spec(doors=2, shelves=0)
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    cups = [c for c in _circles(text) if abs(c[2] * 2 - 35.0) < 0.5]
    sched = drilling_schedule(s)
    n_cup = sum(len(op.holes) for op in sched.ops if "hinge cup" in op.operation)
    assert n_cup > 0
    assert len(cups) == n_cup


# --- shelf-pin rows on the sides -----------------------------------------

def test_side_shelf_pins_drawn(tmp_path):
    s = spec(shelves=2, doors=0)
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    pins = [c for c in _circles(text) if abs(c[2] * 2 - 5.0) < 0.5]
    sched = drilling_schedule(s)
    n_pin = sum(len(op.holes) for op in sched.ops if "shelf-pin" in op.operation)
    assert n_pin > 0
    assert len(pins) == n_pin


# --- total bore count ----------------------------------------------------

def test_total_bores_match_schedule(tmp_path):
    # Every scheduled hole is drawable in the common cabinet shapes (the
    # instance->hand pairing covers both sides and a pair of doors), so the
    # circle count equals the schedule's total.
    for s in (spec(),
              spec(doors=1, drawers=[Drawer(140)], shelves=0),
              spec(cabinet_type=CabinetType.TALL, height=2100, shelves=6)):
        text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
        assert len(_circles(text)) == drilling_schedule(s).total_holes


# --- every bore lands inside its part outline ----------------------------

def test_bores_inside_part_outlines(tmp_path):
    s = spec(doors=2, shelves=2)
    cl = generate_cutlist(s)
    by_id = {p.id: p for p in cl.parts if p.id}
    sheet = SheetSize()
    sheets, _ = pack(_cutlist_items(cl), sheet)
    ops_by_id = holes_by_part_id(drilling_schedule(s))
    gap = 200.0
    drawn = 0
    for s_idx, placements in enumerate(sheets):
        sx = s_idx * (sheet.length + gap)
        for (x, y, l, w, label) in placements:
            part, inst = _placement_part(label, by_id)
            if part is None:
                continue
            ops = ops_by_id.get(part.id)
            if not ops:
                continue
            holes = [h for op in ops_for_instance(ops, inst, part.qty)
                     for h in op.holes]
            for (cx, cy, _h) in place_holes(holes, part.length, part.width,
                                            sx + x, y, l, w):
                drawn += 1
                assert sx + x - 1e-6 <= cx <= sx + x + l + 1e-6
                assert y - 1e-6 <= cy <= y + w + 1e-6
    assert drawn == drilling_schedule(s).total_holes


# --- bores mirrored into the per-part shop drawings ----------------------

def test_drawings_show_door_bores():
    from woodworking_ai.drawings import projected_views, render_svg
    s = spec(doors=2, shelves=1)
    views = projected_views(s)
    front = next(v for v in views if v[0] == "Front elevation")
    boxes = front[3]
    bores = [b for box in boxes for b in (box.bores or [])]
    # 2 doors x 2 hinges = 4 hinge cups, all ⌀35, all inside their door box.
    assert len(bores) == 4
    for box in boxes:
        for (bh, bv, dia) in (box.bores or ()):
            assert abs(dia - 35.0) < 0.5
            assert box.h0 - 1e-6 <= bh <= box.h1 + 1e-6
            assert box.v0 - 1e-6 <= bv <= box.v1 + 1e-6
    assert render_svg(s).count("<circle") == 4
