"""Workbench (G1) — a heavy laminated-top bench with dog holes and a vise."""

import pytest

from woodworking_ai import (
    WorkbenchSpec, Project, Component,
    validate, generate_cutlist, estimate,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, WORKBENCH
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def _wb(**kw) -> WorkbenchSpec:
    base = dict(name="Bench", width=1500, depth=600, height=900, species="beech")
    base.update(kw)
    return WorkbenchSpec(**base)


def test_dispatch_and_roundtrip():
    assert spec_kind(_wb()) == WORKBENCH
    assert WorkbenchSpec.from_dict(_wb(vise_side="right").to_dict()) == _wb(vise_side="right")
    imp = WorkbenchSpec.from_dict({"units": "in", "width": 60, "top_thickness": 3})
    assert imp.width == pytest.approx(60 * MM_PER_IN)


def test_derived_counts():
    assert _wb(width=1500, leg_inset=60).dog_hole_count >= 4
    assert _wb(dog_holes=10).dog_hole_count == 10
    assert _wb(depth=600).lamination_count >= 4
    assert _wb(top_laminations=20).lamination_count == 20


def test_panels_and_laminated_top():
    starts = {p.label.split()[0] for p in panel_layout(_wb())}
    assert {"Top", "Leg", "Apron", "Stretcher", "Shelf"} <= starts
    cl = generate_cutlist(_wb())
    assert any(p.name == "Top lamination" and p.qty >= 4 for p in cl.parts)


def test_vise_and_dogs_hardware_and_joinery():
    cl = generate_cutlist(_wb(vise=True, vise_side="left"))
    hw = " ".join(h.name.lower() for h in cl.hardware)
    assert "vise" in hw and "dog" in hw
    assert any("Vise jaw" == p.name for p in cl.parts)
    ops = " ".join(o.operation for o in joinery_schedule(_wb()).ops).lower()
    assert "draw-bored" in ops and "dog hole" in ops


def test_no_vise():
    cl = generate_cutlist(_wb(vise=False, vise_side="none"))
    assert not any("vise" in h.name.lower() for h in cl.hardware)
    assert not any(p.name == "Vise jaw" for p in cl.parts)


def test_validate():
    assert validate(_wb()).ok
    assert any(i.field == "top_thickness" for i in validate(_wb(top_thickness=30)).warnings)
    assert any(i.field == "stretchers" for i in validate(_wb(stretchers=False)).warnings)
    assert any(i.field == "joinery" for i in validate(_wb(joinery="pocket")).warnings)
    assert not validate(_wb(width=0)).ok


def test_assembly_and_estimate():
    names = [s.name for s in assembly_plan(_wb()).subassemblies]
    assert "Top" in names and "Base" in names
    assert estimate(_wb()).total > 0


def test_built_envelope_matches_spec():
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    for vs in ("left", "front", "none"):
        s = _wb(vise_side=vs)
        d = measure(build_model(s))
        assert d["width"] == pytest.approx(s.width, abs=1.0), vs
        assert d["height"] == pytest.approx(s.height, abs=1.0), vs


def test_inside_project():
    proj = Project(name="Shop", components=[Component(spec=_wb(), x=0)])
    assert validate(proj).ok and estimate(proj).total > 0
