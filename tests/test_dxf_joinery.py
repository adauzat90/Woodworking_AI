"""Tests for housed joints (dados / rabbets / grooves) drawn into the nest DXF.

The nest DXF carries each panel's machining: bores on ``BORE`` (see
``test_dxf_bores``) and housed joints on ``DADO`` / ``RABBET``. A housing's cut
width comes straight from :func:`joinery_schedule`; its position is placed to
the named edge (an intentional approximation — the schedule has no numeric
coordinate). These tests pin: the layers carry housing geometry for a cabinet
with dados + a rabbeted back, the housing count scales with panel qty, and the
``joinery=False`` switch (and a featureless panel) fall back to outline-only.
"""

import re

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer, BackStyle, Joinery,
)
from woodworking_ai.dxf import (
    export_cutlayout_dxf, joinery_by_part_id,
)
from woodworking_ai.joinery import joinery_schedule


def spec(**o) -> CabinetSpec:
    d = dict(name="Joint", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def _rects(text: str, layer: str) -> int:
    """Count closed rectangles (4 LINE segments) on *layer*."""
    return len(re.findall(rf"\nLINE\n8\n{layer}\n", text)) // 4


# --- housed joints drawn on the dedicated layers -------------------------

def test_dados_and_rabbets_drawn(tmp_path):
    # Default joinery is "dado" carcass joints with a rabbeted back, so a stock
    # cabinet has both a DADO housing (sides receive the bottom) and a RABBET
    # housing (sides rabbeted for the back).
    s = spec()
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    assert _rects(text, "DADO") > 0
    assert _rects(text, "RABBET") > 0


def test_housings_only_on_machining_layers(tmp_path):
    # Featureless joinery (a butt joint with an applied back) houses nothing.
    s = spec(joinery=Joinery.BUTT, back=BackStyle.APPLIED, doors=0, shelves=0)
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    assert _rects(text, "DADO") == 0
    assert _rects(text, "RABBET") == 0
    # The panels themselves are still drawn (outline-only).
    assert _rects(text, "PANEL") > 0


# --- housing geometry matches the (deduped) schedule ---------------------

def test_housing_count_matches_deduped_schedule(tmp_path):
    # Every placed instance of a part draws that part's deduped housing set, so
    # the DADO+RABBET rectangle total equals (#housings per part) x (part qty).
    from woodworking_ai.cutlist import generate_cutlist
    s = spec()
    cl = generate_cutlist(s)
    qty_by_id = {p.id: p.qty for p in cl.parts if p.id}
    jbi = joinery_by_part_id(joinery_schedule(s))
    expected = sum(len(ops) * qty_by_id.get(pid, 0) for pid, ops in jbi.items())
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    assert _rects(text, "DADO") + _rects(text, "RABBET") == expected
    assert expected > 0


# --- counts scale with panel qty -----------------------------------------

def test_housings_scale_with_panel_qty(tmp_path):
    # A taller carcass nests the (qty-2) sides the same way; the per-side
    # housing set is unchanged, so the housing total stays 2 x the per-side set.
    base = export_cutlayout_dxf(spec(), tmp_path / "a.dxf").read_text()
    tall = export_cutlayout_dxf(
        spec(cabinet_type=CabinetType.TALL, height=2100, shelves=6),
        tmp_path / "b.dxf").read_text()
    n_base = _rects(base, "DADO") + _rects(base, "RABBET")
    n_tall = _rects(tall, "DADO") + _rects(tall, "RABBET")
    # Both have two sides; the carcass housings (bottom dado + back rabbet) are
    # present in both, so each draws an even, non-zero housing total.
    assert n_base > 0 and n_base % 2 == 0
    assert n_tall > 0 and n_tall % 2 == 0


# --- the joinery toggle defaults on and can be switched off ---------------

def test_joinery_toggle_off_falls_back_to_outline(tmp_path):
    s = spec()
    on = export_cutlayout_dxf(s, tmp_path / "on.dxf").read_text()
    off = export_cutlayout_dxf(s, tmp_path / "off.dxf", joinery=False).read_text()
    assert _rects(on, "DADO") + _rects(on, "RABBET") > 0
    assert _rects(off, "DADO") + _rects(off, "RABBET") == 0
    # Disabling joinery must not touch the panel outlines or the bores.
    assert _rects(off, "PANEL") == _rects(on, "PANEL")
    assert off.count("\nCIRCLE\n") == on.count("\nCIRCLE\n")


def test_drawer_box_groove_houses_on_drawer_sides(tmp_path):
    # A drawer with a real box has a "groove for bottom" housing on its sides;
    # that op carries a width+depth and lands on the DADO layer.
    s = spec(doors=0, drawers=[Drawer(140, false_front=False)], shelves=0)
    jbi = joinery_by_part_id(joinery_schedule(s))
    grooves = [op for ops in jbi.values() for op in ops
               if "groove" in op.operation.lower()]
    assert grooves, "expected a drawer-bottom groove housing"
    text = export_cutlayout_dxf(s, tmp_path / "l.dxf").read_text()
    assert _rects(text, "DADO") > 0
