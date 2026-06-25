"""Cutting / charcuterie board (G1) — an edge-glued strip panel.

Proves the cutting-board leaf type flows through the whole pipeline with no
generic-stage edit, derives its strip glue-up, supports a two-species pattern
and end-grain construction, and gives food-safe advisories.
"""

import pytest

from woodworking_ai import (
    CuttingBoardSpec, GrainStyle, Project, Component,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, CUTTING_BOARD
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def _board(**kw) -> CuttingBoardSpec:
    base = dict(name="Board", length=450, width=300, thickness=38,
                species="hard_maple")
    base.update(kw)
    return CuttingBoardSpec(**base)


def test_dispatch_and_spec_from_dict():
    assert spec_kind(_board()) == CUTTING_BOARD
    assert isinstance(spec_from_dict({"kind": "cutting_board", "width": 300}),
                      CuttingBoardSpec)
    assert isinstance(spec_from_dict({"kind": "board", "width": 300}),
                      CuttingBoardSpec)


def test_roundtrip_preserves_grain_style():
    spec = _board(grain_style="end_grain", species_b="walnut")
    again = CuttingBoardSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.grain_style == GrainStyle.END_GRAIN


def test_imperial_on_load():
    spec = CuttingBoardSpec.from_dict(
        {"units": "in", "length": 18, "width": 12, "thickness": 1.5})
    assert spec.units == "mm"
    assert spec.length == pytest.approx(18 * MM_PER_IN)
    assert spec.thickness == pytest.approx(1.5 * MM_PER_IN)


def test_strip_count_auto_and_explicit():
    assert _board(width=300, strips=0).strip_count >= 3
    b = _board(width=300, strips=6)
    assert b.strip_count == 6
    assert b.strip_width == pytest.approx(50.0)


def test_panels_tile_the_width():
    panels = panel_layout(_board(strips=6))
    assert len(panels) == 6
    assert all(p.label.startswith("Strip") for p in panels)


def test_single_species_cutlist_one_strip_part():
    cl = generate_cutlist(_board(species_b=""))
    strip_parts = [p for p in cl.parts if p.name.startswith("Strip")]
    assert len(strip_parts) == 1
    assert strip_parts[0].qty == _board().strip_count
    # Always carries a food-safe oil line.
    assert any("oil" in h.name.lower() for h in cl.hardware)


def test_two_species_splits_strips():
    cl = generate_cutlist(_board(species_b="walnut", strips=7))
    names = [p.name for p in cl.parts if p.name.startswith("Strip")]
    assert len(names) == 2
    qtys = sorted(p.qty for p in cl.parts if p.name.startswith("Strip"))
    assert qtys == [3, 4]            # 7 strips alternate 4 + 3


def test_feet_optional():
    assert any("feet" in h.name.lower() for h in generate_cutlist(_board(feet=True)).hardware)
    assert not any("feet" in h.name.lower() for h in generate_cutlist(_board(feet=False)).hardware)


def test_validate_sane_board_passes():
    assert validate(_board()).ok


def test_validate_warns_thin_end_grain():
    res = validate(_board(grain_style="end_grain", thickness=20))
    assert any(i.field == "thickness" for i in res.warnings)


def test_validate_warns_non_food_safe_finish():
    res = validate(_board(finish="paint"))
    assert any(i.field == "finish" for i in res.warnings)


def test_validate_warns_open_pore_species():
    res = validate(_board(species="red_oak"))
    assert any(i.field == "species" for i in res.warnings)


def test_validate_warns_juice_groove_too_thin():
    res = validate(_board(thickness=20, juice_groove=True))
    assert any(i.field == "juice_groove" for i in res.warnings)


def test_joinery_has_glueup_and_optional_groove():
    ops = joinery_schedule(_board(juice_groove=True)).ops
    text = " ".join(o.operation for o in ops).lower()
    assert "edge glue-up" in text
    assert "juice groove" in text


def test_end_grain_adds_crosscut_reglue():
    ops = joinery_schedule(_board(grain_style="end_grain")).ops
    assert any("re-glue" in o.operation.lower() for o in ops)
    plan = assembly_plan(_board(grain_style="end_grain"))
    assert any("end grain" in s.name.lower() for s in plan.subassemblies)


def test_estimate_and_project():
    assert estimate(_board()).total > 0
    proj = Project(name="Gifts", components=[
        Component(spec=_board(name="A"), x=0, label="A"),
        Component(spec=_board(name="B"), x=500, label="B"),
    ])
    assert validate(proj).ok
    assert estimate(proj).total > 0


def test_built_envelope_matches_spec():
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    spec = _board()
    dims = measure(build_model(spec))
    assert dims["width"] == pytest.approx(spec.width, abs=1.0)
    assert dims["depth"] == pytest.approx(spec.length, abs=1.0)
    assert dims["height"] == pytest.approx(spec.thickness, abs=1.0)
