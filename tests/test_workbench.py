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


def test_dog_holes_dict_does_not_crash():
    # A hand-written spec may pass dog_holes as an object by mistake; it must
    # coerce to auto (0) instead of crashing the derived-count math.
    from woodworking_ai import spec_from_dict
    wb = spec_from_dict({"kind": "workbench", "width": 1800, "leg_inset": 80,
                         "dog_holes": {"spacing": 150, "dia": 19}})
    assert wb.dog_holes == 0
    assert wb.dog_hole_count >= 4          # falls back to the auto row
    assert validate(wb).ok


def test_top_fixing_is_recognized_and_roundtrips():
    from woodworking_ai.dsl import TopFixing
    wb = _wb(top_fixing="floating")
    assert wb.top_fixing == TopFixing.FLOATING
    assert WorkbenchSpec.from_dict(wb.to_dict()) == wb


def test_dog_holes_appear_in_drilling_schedule():
    from woodworking_ai.drilling import drilling_schedule
    sched = drilling_schedule(_wb(width=1800, leg_inset=80, dog_holes=10))
    dog_ops = [o for o in sched.ops if "dog" in o.operation.lower()]
    assert dog_ops and sum(len(o.holes) for o in dog_ops) == 10


def test_solid_bench_build_time_is_not_trivial():
    # Regression: a solid laminated bench used to be milled as sheet goods and
    # estimated at ~2h; it must now reflect real stock prep + the top glue-up.
    from woodworking_ai.planning import plan
    p = plan(_wb(width=1800, depth=600, top_thickness=120))
    assert p["time"]["total"] > 6.0
    assert p["time"]["hours_by_phase"]["assembly"] > 2.0
