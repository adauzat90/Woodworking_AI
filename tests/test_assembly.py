"""Sub-assemblies: nestable groups and define-once / place-many reuse.

Covers the two capabilities the assembly layer adds on top of a flat Project:
  * nesting — a component's spec may itself be a group, and every pipeline stage
    (validate / cut list / estimate / drilling / geometry / critic) recurses
    into it, so a group-of-groups needs no special handling;
  * reuse — a group declares named sub-assemblies under ``definitions`` and a
    component places an independent copy of one by ``ref``.
"""

import pytest

from woodworking_ai import (
    CabinetSpec, Component, Assembly, ComponentGroup, Project,
    spec_from_dict, validate, generate_cutlist, estimate, drilling_schedule,
)
from woodworking_ai.dsl import DSL_SCHEMA_HINT
from woodworking_ai.geometry import panel_layout, project_layout, footprint_corners


def _bank() -> Assembly:
    """A two-cabinet drawer bank, used as a reusable sub-assembly."""
    return Assembly(name="DrawerBank", components=[
        Component(spec=CabinetSpec(name="D1", width=600), x=0, label="d1"),
        Component(spec=CabinetSpec(name="D2", width=600), x=600, label="d2"),
    ])


def _kitchen_with_bank() -> Project:
    return Project(name="Kitchen", components=[
        Component(spec=_bank(), x=0, y=0, label="BANK"),
        Component(spec=CabinetSpec(name="Sink", width=900), x=1200, label="SINK"),
    ])


# --- nesting: every stage recurses into a sub-assembly ----------------------

def test_assembly_is_a_component_group():
    assert isinstance(Assembly(), ComponentGroup)
    assert isinstance(Project(), ComponentGroup)


def test_nested_cutlist_is_sum_of_children():
    proj = _kitchen_with_bank()
    cl = generate_cutlist(proj)
    total = sum(len(generate_cutlist(c.spec).parts) for c in proj.components)
    assert len(cl.parts) == total
    # Parts carry the nested tag path (project tag · sub-component tag · part).
    assert any("BANK" in p.name and "·" in p.name for p in cl.parts)


def test_nested_panel_layout_is_sum_of_children():
    proj = _kitchen_with_bank()
    panels = project_layout(proj)
    assert len(panels) == sum(len(panel_layout(c.spec)) for c in proj.components)
    # panel_layout dispatches a group the same as project_layout.
    assert len(panel_layout(proj)) == len(panels)


def test_nested_validate_estimate_drilling_recurse():
    proj = _kitchen_with_bank()
    assert validate(proj).ok
    assert estimate(proj).total > 0
    # Drilling aggregates every leaf cabinet, including those inside the bank.
    one = drilling_schedule(CabinetSpec(name="D1", width=600)).total_holes
    assert drilling_schedule(proj).total_holes >= 2 * one > 0


def test_assembly_can_nest_in_an_assembly():
    inner = Assembly(name="Inner", components=[
        Component(spec=CabinetSpec(width=600), x=0)])
    outer = Assembly(name="Outer", components=[
        Component(spec=inner, x=0), Component(spec=inner, x=0, y=1000)])
    proj = Project(components=[Component(spec=outer, x=0)])
    # Two copies of a one-cabinet inner assembly -> two cabinets' worth of parts.
    assert len(generate_cutlist(proj).parts) == \
        2 * len(generate_cutlist(CabinetSpec(width=600)).parts)
    assert validate(proj).ok


# --- placement: a placed group transforms as one unit -----------------------

def test_placing_a_group_translates_all_its_panels():
    bank = _bank()
    at0 = project_layout(Project(components=[Component(spec=bank, x=0, y=0)]))
    at2k = project_layout(Project(components=[Component(spec=bank, x=0, y=2000)]))
    y0 = min(p.center[1] for p in at0)
    y2 = min(p.center[1] for p in at2k)
    assert round(y2 - y0) == 2000


def test_group_footprint_reflects_real_outline():
    # A 2×600 bank reads as ~1200 wide, ~560 deep — not a missing-width zero box.
    comp = Component(spec=_bank(), x=0, y=0)
    fp = footprint_corners(comp)
    xs = [p[0] for p in fp]
    ys = [p[1] for p in fp]
    assert round(max(xs) - min(xs)) == 1200
    assert 555 <= (max(ys) - min(ys)) <= 580


def test_overlapping_sub_assemblies_are_flagged():
    a = Assembly(components=[Component(spec=CabinetSpec(width=600, depth=560), x=0)])
    proj = Project(components=[
        Component(spec=a, x=0, y=0),
        Component(spec=a, x=200, y=100),     # driven into the first group
    ])
    res = validate(proj)
    assert not res.ok
    assert any(i.field == "placement" for i in res.errors)


# --- reuse: definitions + ref ----------------------------------------------

def _reuse_payload() -> dict:
    return {
        "kind": "project", "name": "Reuse",
        "definitions": {
            "wall_pair": {
                "kind": "assembly", "name": "WallPair",
                "components": [
                    {"spec": {"cabinet_type": "wall", "width": 600,
                              "toe_kick": None}, "x": 0},
                    {"spec": {"cabinet_type": "wall", "width": 600,
                              "toe_kick": None}, "x": 600},
                ],
            },
        },
        "components": [
            {"ref": "wall_pair", "x": 0, "y": 0, "label": "P1"},
            {"ref": "wall_pair", "x": 0, "y": 2000, "label": "P2"},
        ],
    }


def test_ref_resolves_to_the_named_definition():
    p = spec_from_dict(_reuse_payload())
    assert isinstance(p, Project) and len(p.components) == 2
    assert all(c.ref == "wall_pair" for c in p.components)
    assert all(isinstance(c.spec, Assembly) for c in p.components)


def test_each_ref_is_an_independent_copy():
    p = spec_from_dict(_reuse_payload())
    p.components[0].spec.components[0].spec.width = 999
    # Mutating one placement must not bleed into its sibling.
    assert p.components[1].spec.components[0].spec.width == 600


def test_unknown_ref_raises():
    with pytest.raises(ValueError):
        spec_from_dict({"kind": "project",
                        "components": [{"ref": "missing"}]})


def test_cyclic_definitions_raise():
    with pytest.raises(ValueError):
        spec_from_dict({
            "kind": "project",
            "definitions": {
                "a": {"kind": "assembly", "components": [{"ref": "b"}]},
                "b": {"kind": "assembly", "components": [{"ref": "a"}]},
            },
            "components": [{"ref": "a"}],
        })


# --- serialization ----------------------------------------------------------

def test_factory_routes_assembly():
    a = spec_from_dict({"kind": "assembly", "name": "Bank", "components": [
        {"spec": {"cabinet_type": "base", "width": 600}, "x": 0}]})
    assert isinstance(a, Assembly) and a.name == "Bank"


def test_inline_nested_project_roundtrips():
    p = _kitchen_with_bank()
    assert Project.from_json(p.to_json()).to_dict() == p.to_dict()


def test_reuse_roundtrips_and_stays_terse():
    p = spec_from_dict(_reuse_payload())
    d = p.to_dict()
    # Placements serialize as a ref (no inline spec); the spec lives once.
    assert d["components"][0]["ref"] == "wall_pair"
    assert "spec" not in d["components"][0]
    assert "wall_pair" in d["definitions"]
    # And the whole thing round-trips byte-for-byte through the factory.
    assert spec_from_dict(d).to_dict() == d


# --- the agent path advertises the capability -------------------------------

def test_schema_hint_describes_projects_and_assemblies():
    for token in ('"kind": "project"', '"kind": "assembly"',
                  '"definitions"', '"ref"'):
        assert token in DSL_SCHEMA_HINT


# --- critic flows through a nested group ------------------------------------

def test_critique_passes_for_nested_spaced_run():
    from woodworking_ai.agents.critic import critique
    crit = critique(_kitchen_with_bank())
    assert crit.ok
    assert crit.report["interference_count"] == 0


def test_build_dispatches_a_top_level_assembly():
    from woodworking_ai.builder import build_model, build_project
    a = Assembly(name="Bank", components=[
        Component(spec=CabinetSpec(width=600), x=0),
        Component(spec=CabinetSpec(width=600), x=600)])
    try:
        import build123d  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError):
            build_project(a)
        return
    from woodworking_ai.builder import measure
    assert measure(build_model(a))["width"] == pytest.approx(1200.0, abs=1.0)
