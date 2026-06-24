"""The Project/assembly layer: placement, combined cut list, validation, cost."""

import pytest

from woodworking_ai import (
    CabinetSpec, TableSpec, Component, Project, spec_from_dict, validate,
    generate_cutlist, estimate,
)


def _kitchen() -> Project:
    return Project(name="Kitchen", components=[
        Component(spec=CabinetSpec(name="Sink", width=900), x=0, label="B1"),
        Component(spec=CabinetSpec(name="Drawers", width=600,
                                   drawers=[]), x=900, label="B2"),
        Component(spec=TableSpec(name="Island"), x=1600, label="ISL"),
    ])


def test_factory_routes_project():
    p = spec_from_dict({"kind": "project", "components": [
        {"label": "A", "spec": {"cabinet_type": "base", "width": 600}}]})
    assert isinstance(p, Project) and len(p.components) == 1
    assert isinstance(p.components[0].spec, CabinetSpec)


def test_project_roundtrips():
    p = _kitchen()
    assert Project.from_json(p.to_json()).to_dict() == p.to_dict()


def test_combined_cutlist_tags_parts_by_component():
    cl = generate_cutlist(_kitchen())
    names = [p.name for p in cl.parts]
    assert any(n.startswith("B1: ") for n in names)
    assert any(n.startswith("ISL: ") for n in names)
    # The combined list is the sum of the components' parts.
    total = sum(len(generate_cutlist(c.spec).parts) for c in _kitchen().components)
    assert len(cl.parts) == total
    assert cl.sheet_area_m2 > 0


def test_project_validation_aggregates_and_prefixes():
    # A too-narrow cabinet errors; the field is tagged with its component.
    p = Project(components=[Component(spec=CabinetSpec(width=30), label="BAD")])
    res = validate(p)
    assert not res.ok
    assert any(i.field.startswith("BAD.") for i in res.errors)


def test_project_detects_placement_overlap():
    p = Project(components=[
        Component(spec=CabinetSpec(width=900), x=0, label="A"),
        Component(spec=CabinetSpec(width=900), x=500, label="B"),  # overlaps A
    ])
    res = validate(p)
    assert not res.ok
    assert any(i.field == "placement" for i in res.errors)


def test_project_placement_ok_when_spaced():
    p = Project(components=[
        Component(spec=CabinetSpec(width=900), x=0, label="A"),
        Component(spec=CabinetSpec(width=600), x=900, label="B"),
    ])
    assert validate(p).ok


def test_project_estimate_sums_components():
    p = _kitchen()
    whole = estimate(p)
    parts = [estimate(c.spec) for c in p.components]
    assert whole.total == pytest.approx(sum(e.total for e in parts))
    assert whole.total_sheets == sum(e.total_sheets for e in parts)
    assert "Cost estimate" in whole.report_text()


# --- assembled geometry (the single-3D-model step) --------------------------

def test_project_layout_places_components_in_one_frame():
    from woodworking_ai.geometry import project_layout, panel_layout
    p = Project(components=[
        Component(spec=CabinetSpec(name="A", width=900), x=0, label="B1"),
        Component(spec=CabinetSpec(name="B", width=600), x=900, label="B2")])
    panels = project_layout(p)
    # Combined layout is exactly the sum of the per-component layouts.
    assert len(panels) == sum(len(panel_layout(c.spec)) for c in p.components)
    # Parts are tagged by component, and the run spans both cabinets in X.
    assert all(" · " in pan.label for pan in panels)
    xmin = min(pan.bounds()[0][0] for pan in panels)
    xmax = max(pan.bounds()[0][1] for pan in panels)
    assert xmin == pytest.approx(0.0, abs=1.0)
    assert xmax == pytest.approx(1500.0, abs=1.0)


def test_panel_layout_dispatches_project():
    from woodworking_ai.geometry import panel_layout, project_layout
    p = _kitchen()
    assert len(panel_layout(p)) == len(project_layout(p))


def test_critique_project_passes_for_spaced_run():
    from woodworking_ai.agents.critic import critique
    p = Project(components=[
        Component(spec=CabinetSpec(width=900), x=0, label="A"),
        Component(spec=CabinetSpec(width=600), x=900, label="B")])
    crit = critique(p)
    assert crit.ok
    assert crit.report["interference_count"] == 0
    assert crit.report["component_count"] == 2


def test_critique_project_flags_colliding_cabinets():
    from woodworking_ai.agents.critic import critique
    p = Project(components=[
        Component(spec=CabinetSpec(width=900), x=0, label="A"),
        Component(spec=CabinetSpec(width=900), x=300, label="B")])  # overlap
    crit = critique(p)
    assert not crit.ok
    assert crit.report["interference_count"] > 0
    assert any(i.kind == "interference" for i in crit.errors)


def test_build_project_builds_or_skips_gracefully():
    from woodworking_ai.builder import build_project, build_model, measure
    p = Project(name="Run", components=[
        Component(spec=CabinetSpec(width=900), x=0, label="A"),
        Component(spec=CabinetSpec(width=600), x=900, label="B")])
    try:
        import build123d  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError):
            build_project(p)
        return
    model = build_project(p)
    dims = measure(model)
    assert dims["width"] == pytest.approx(1500.0, abs=1.0)
    # build_model dispatches a Project to build_project.
    assert measure(build_model(p))["width"] == pytest.approx(1500.0, abs=1.0)
