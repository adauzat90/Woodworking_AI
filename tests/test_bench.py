"""Bench / stool (H1) — a seat on four legs with aprons + stretchers.

Proves the bench leaf type (a low-table superset) flows through the whole
pipeline with no edit to any generic stage.
"""

import pytest

from woodworking_ai import (
    BenchSpec, Joinery, Project, Component,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, BENCH
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai import furniture


def _bench(**kw) -> BenchSpec:
    base = dict(name="Dining Bench", width=1200, depth=350, height=450,
                species="ash")
    base.update(kw)
    return BenchSpec(**base)


def test_dispatch_kind_and_registry():
    assert spec_kind(_bench()) == BENCH
    assert furniture.is_registered(BENCH)


def test_spec_from_dict_routes_bench_and_stool_alias():
    assert isinstance(spec_from_dict({"kind": "bench", "width": 900}), BenchSpec)
    assert isinstance(spec_from_dict({"kind": "stool", "width": 350}), BenchSpec)


def test_bench_kind_wins_over_table_heuristic():
    # A bench carries `leg`/`top_thickness` like a table; the explicit kind must
    # still route it to a BenchSpec.
    spec = spec_from_dict({"kind": "bench", "width": 1000, "leg": 45,
                           "top_thickness": 30})
    assert isinstance(spec, BenchSpec)


def test_roundtrip_to_from_dict():
    spec = _bench(joinery="domino", stretchers=False)
    again = BenchSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.joinery == Joinery.DOMINO


def test_imperial_on_load_converts_to_mm():
    spec = BenchSpec.from_dict(
        {"units": "in", "width": 48, "depth": 14, "height": 18, "leg": 1.75})
    assert spec.units == "mm"
    assert spec.width == pytest.approx(48 * MM_PER_IN)
    assert spec.leg == pytest.approx(1.75 * MM_PER_IN)


def test_panels_seat_legs_aprons_stretchers():
    labels = [p.label for p in panel_layout(_bench())]
    assert "Seat" in labels
    assert sum(1 for l in labels if l.startswith("Leg")) == 4
    assert labels.count("Apron long") == 2
    assert labels.count("Apron short") == 2
    assert labels.count("Stretcher") == 2


def test_no_stretchers_when_disabled():
    labels = [p.label for p in panel_layout(_bench(stretchers=False))]
    assert "Stretcher" not in labels


def test_cutlist_parts_and_hardware():
    cl = generate_cutlist(_bench())
    names = [p.name for p in cl.parts]
    assert "Seat" in names and "Leg" in names and "Stretcher" in names
    assert all(p.id for p in cl.parts)
    assert any("bracket" in h.name.lower() for h in cl.hardware)


def test_validate_sane_bench_passes():
    assert validate(_bench()).ok


def test_validate_rejects_nonpositive_dims():
    assert not validate(_bench(width=0)).ok


def test_validate_warns_weak_joinery():
    res = validate(_bench(joinery="butt"))
    assert any(i.field == "joinery" for i in res.warnings)


def test_tall_stool_without_stretchers_warns():
    res = validate(_bench(width=350, depth=350, height=650, stretchers=False))
    assert any(i.field == "stretchers" for i in res.warnings)


def test_joinery_has_leg_apron_and_stretcher():
    ops = [o.operation for o in joinery_schedule(_bench()).ops]
    assert "leg-to-apron joint" in ops
    assert "leg-to-stretcher joint" in ops


def test_assembly_plan_base_seat_final():
    names = [s.name for s in assembly_plan(_bench()).subassemblies]
    assert names == ["Base", "Seat", "Final assembly"]


def test_estimate_prices_the_bench():
    assert estimate(_bench()).total > 0


def test_bench_inside_a_project():
    proj = Project(name="Seating", components=[
        Component(spec=_bench(name="A", width=1000), x=0, label="A"),
        Component(spec=_bench(name="B", width=1000), x=1500, label="B"),
    ])
    assert validate(proj).ok
    assert estimate(proj).total > 0
    assert len(panel_layout(proj)) > 0
