"""Desk (G1) — a legged writing desk with apron drawers + modesty panel."""

import pytest

from woodworking_ai import (
    DeskSpec, Project, Component,
    validate, generate_cutlist, estimate,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, DESK
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def _desk(**kw) -> DeskSpec:
    base = dict(name="Desk", width=1200, depth=600, height=740,
                species="white_oak")
    base.update(kw)
    return DeskSpec(**base)


def test_dispatch_and_roundtrip():
    assert spec_kind(_desk()) == DESK
    assert DeskSpec.from_dict(_desk(drawers=2).to_dict()) == _desk(drawers=2)
    imp = DeskSpec.from_dict({"units": "in", "width": 48, "height": 29})
    assert imp.width == pytest.approx(48 * MM_PER_IN)


def test_drawers_side_by_side_and_grommet_and_modesty():
    labels = [p.label for p in panel_layout(_desk(drawers=3))]
    assert sum(l.startswith("Drawer front") for l in labels) == 3
    assert any("Modesty" in l for l in labels)
    cl = generate_cutlist(_desk(grommet=True))
    assert any("grommet" in h.name.lower() for h in cl.hardware)
    assert any(o.operation.startswith("bore cable") for o in joinery_schedule(_desk()).ops)


def test_no_drawer_adds_front_apron():
    labels = [p.label for p in panel_layout(_desk(drawers=0))]
    assert "Apron front" in labels
    assert not any("Drawer" in l for l in labels)


def test_modesty_optional():
    assert not any("Modesty" in p.label for p in panel_layout(_desk(modesty_panel=False)))


def test_validate():
    assert validate(_desk()).ok
    assert any(i.field == "height" for i in validate(_desk(height=500)).warnings)
    assert any(i.field == "joinery" for i in validate(_desk(joinery="butt")).warnings)
    assert not validate(_desk(width=0)).ok


def test_assembly_and_estimate():
    names = [s.name for s in assembly_plan(_desk()).subassemblies]
    assert "Base" in names and "Drawers" in names
    assert estimate(_desk()).total > 0


def test_built_envelope_matches_spec():
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    s = _desk()
    d = measure(build_model(s))
    assert d["width"] == pytest.approx(s.width, abs=1.0)
    assert d["depth"] == pytest.approx(s.depth, abs=1.0)
    assert d["height"] == pytest.approx(s.height, abs=1.0)


def test_inside_project():
    proj = Project(name="Office", components=[Component(spec=_desk(), x=0)])
    assert validate(proj).ok and estimate(proj).total > 0
