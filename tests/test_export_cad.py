"""Tests for DXF cut-layout export (pure) and real CAD export (build123d)."""

import pytest

from woodworking_ai import CabinetSpec, CabinetType, Material, ToeKick, Drawer
from woodworking_ai.dxf import export_cutlayout_dxf, _pack_positions
from woodworking_ai.estimator import SheetSize


def spec(**o) -> CabinetSpec:
    d = dict(name="Exp", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- DXF (no CAD dependency) ---------------------------------------------

def test_dxf_writes_valid_envelope(tmp_path):
    path = export_cutlayout_dxf(spec(), tmp_path / "layout.dxf")
    text = path.read_text()
    assert text.startswith("0\nSECTION")
    assert text.rstrip().endswith("EOF")
    assert "ENTITIES" in text


def test_dxf_contains_part_labels(tmp_path):
    text = export_cutlayout_dxf(spec(), tmp_path / "l.dxf").read_text()
    assert "Side" in text and "Door" in text


def test_pack_positions_stay_within_sheet():
    sheet = SheetSize()
    items = [(p, q, f"part{i}") for i, (p, q) in
             enumerate([(600, 400), (800, 500), (1200, 600)])]
    sheets, oversize = _pack_positions(items, sheet)
    for placements in sheets:
        for (x, y, l, w, _) in placements:
            assert x + l <= sheet.length + 1e-6
            assert y + w <= sheet.width + 1e-6
    assert oversize == []


def test_pack_positions_flags_oversize():
    sheets, oversize = _pack_positions([(3000, 400, "huge")], SheetSize())
    assert oversize == ["huge"]


def test_big_cabinet_spills_to_multiple_sheets(tmp_path):
    tall = spec(cabinet_type=CabinetType.TALL, height=2100, shelves=6,
                doors=2, toe_kick=ToeKick(100, 50))
    text = export_cutlayout_dxf(tall, tmp_path / "t.dxf").read_text()
    assert text.count("Sheet ") >= 2


# --- real CAD export (build123d) -----------------------------------------

def test_real_step_stl_glb_export(tmp_path):
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    from woodworking_ai import exporters

    model = build_model(spec(drawers=[Drawer(140)]))
    dims = measure(model)
    assert dims["width"] == pytest.approx(600)
    for fn, ext in ((exporters.export_step, "step"),
                    (exporters.export_stl, "stl"),
                    (exporters.export_glb, "glb")):
        p = fn(model, tmp_path / f"c.{ext}")
        assert p.exists() and p.stat().st_size > 0


def test_real_geometry_matches_critic_envelope(tmp_path):
    pytest.importorskip("build123d")
    from woodworking_ai.agents.critic import critique
    # use_cad cross-checks the real B-Rep against the analytical layout.
    crit = critique(spec(), use_cad=True, brep=True)
    assert crit.ok
    assert "measured" in crit.report
    assert crit.report["brep_interference_count"] == 0
