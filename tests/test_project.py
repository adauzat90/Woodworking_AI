"""The Project/assembly layer: placement, combined cut list, validation, cost."""

import pytest

from woodworking_ai import (
    CabinetSpec, TableSpec, Component, Project, spec_from_dict, validate,
    generate_cutlist, estimate, place_run,
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
    assert any(n.startswith("B1 · ") for n in names)
    assert any(n.startswith("ISL · ") for n in names)
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


# --- corner joining: L/U runs, oriented footprints --------------------------

def test_place_run_straight_steps_by_width():
    run = place_run([CabinetSpec(width=600), CabinetSpec(width=400)],
                    start=(0, 0), angle=0)
    assert [round(c.x) for c in run] == [0, 600]
    assert all(c.rotation == 0 and c.y == 0 for c in run)


def test_place_run_perpendicular_turns_the_corner():
    run = place_run([CabinetSpec(width=600), CabinetSpec(width=600)],
                    start=(1200, 0), angle=90)
    # Along +Y: x is constant, y steps by width, each piece rotated 90°.
    assert all(c.rotation == 90 and c.x == 1200 for c in run)
    assert [round(c.y) for c in run] == [0, 600]


def test_footprint_is_oriented_under_rotation():
    from woodworking_ai.geometry import footprint_corners
    c = Component(spec=CabinetSpec(width=600, depth=560), x=0, y=0, rotation=90)
    xs = [p[0] for p in footprint_corners(c)]
    ys = [p[1] for p in footprint_corners(c)]
    # Rotated 90°: width now runs along Y (~600), depth along X (~560).
    assert round(max(ys) - min(ys)) == 600
    assert round(max(xs) - min(xs)) == 560


def test_l_run_validates_without_false_collision():
    runA = place_run([CabinetSpec(width=600, name="A1"),
                      CabinetSpec(width=600, name="A2")], start=(0, 0), angle=0)
    runB = place_run([CabinetSpec(width=600, name="B1"),
                      CabinetSpec(width=600, name="B2")],
                     start=(1200, 560), angle=90)
    proj = Project(name="L", components=runA + runB)
    assert validate(proj).ok                      # perpendicular runs don't clash


def test_inner_corner_overlap_is_detected():
    runA = place_run([CabinetSpec(width=600, name="A1"),
                      CabinetSpec(width=600, name="A2")], start=(0, 0), angle=0)
    # Run B turned into run A's footprint at the corner -> collision.
    bad = Project(components=runA + place_run(
        [CabinetSpec(width=600, name="X")], start=(600, 200), angle=90))
    res = validate(bad)
    assert not res.ok
    assert any(i.field == "placement" for i in res.errors)


def test_critique_detects_rotated_run_collision():
    # The panel-AABB test skips rotated panels; the footprint check must still
    # catch a perpendicular cabinet driven into a straight one.
    from woodworking_ai.agents.critic import critique
    proj = Project(components=[
        Component(spec=CabinetSpec(width=600, depth=560), x=0, y=0, rotation=0),
        Component(spec=CabinetSpec(width=600, depth=560), x=300, y=100,
                  rotation=90)])
    crit = critique(proj)
    assert not crit.ok and crit.report["interference_count"] > 0


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


def test_project_drilling_aggregates_per_component():
    from woodworking_ai.drilling import drilling_schedule
    p = Project(components=[
        Component(spec=CabinetSpec(width=600, shelves=2, doors=2), x=0, label="B1"),
        Component(spec=CabinetSpec(width=600, shelves=2, doors=2), x=600, label="B2")])
    sched = drilling_schedule(p)
    one = drilling_schedule(CabinetSpec(width=600, shelves=2, doors=2)).total_holes
    assert one > 0
    assert sched.total_holes == 2 * one          # not silently empty
    assert any(op.part.startswith("B1 · ") for op in sched.ops)


def test_full_pipeline_composes_corner_run_table_imperial():
    """Everything together: an L-run with a corner cabinet + a table island,
    through validate / cut list (imperial) / estimate / critic / drilling."""
    from woodworking_ai.agents.critic import critique
    from woodworking_ai.drilling import drilling_schedule
    corner = CabinetSpec.from_dict({"cabinet_type": "corner_diagonal",
                                    "width": 900, "depth": 600, "corner_cut": 450,
                                    "name": "Corner", "shelves": 1})
    base = CabinetSpec.from_dict({"cabinet_type": "base", "width": 600,
                                  "doors": 2, "shelves": 1, "name": "Base"})
    runA = place_run([corner, base], start=(0, 0), angle=0)
    island = Component(spec=TableSpec(name="Island", width=1200, depth=800),
                       x=0, y=2000, label="ISL")
    proj = Project(name="Kitchen", components=runA + [island])

    assert validate(proj).ok
    cl = generate_cutlist(proj)
    names = [p.name for p in cl.parts]
    assert any(n.startswith("Corner · ") for n in names)
    assert any(n.startswith("ISL · ") for n in names)
    assert cl.to_csv("imperial").splitlines()[0].endswith("material,grain,notes")
    assert "length_in" in cl.to_csv("imperial").splitlines()[0]
    assert estimate(proj).total > 0
    assert critique(proj).ok
    assert drilling_schedule(proj).total_holes > 0
