"""Guard the spec-type dispatch unification (Phase 8).

The pipeline's type ladder (ApplianceVoid -> ComponentGroup -> TableSpec ->
cabinet) is now defined once in ``dispatch.spec_kind``; every stage routes
through it instead of re-implementing isinstance checks. These tests pin that
single source down and prove a new ComponentGroup subclass flows through the
whole pipeline without editing any stage.
"""

from dataclasses import dataclass

import woodworking_ai.dispatch as dispatch
from woodworking_ai import (
    CabinetSpec, TableSpec, Component, Project, Assembly,
    validate, generate_cutlist, estimate,
)
from woodworking_ai.dsl import ApplianceVoid, ComponentGroup
from woodworking_ai.dispatch import spec_kind, is_group, VOID, GROUP, TABLE, CABINET
from woodworking_ai.geometry import panel_layout, PanelBox
from woodworking_ai import furniture
from woodworking_ai.cutlist import CutList, Part
from woodworking_ai.validator import Issue
from woodworking_ai.joinery import JoineryOp, joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def test_spec_kind_covers_every_type():
    assert spec_kind(ApplianceVoid(name="gap", width=600)) == VOID
    assert spec_kind(Project(name="p")) == GROUP
    assert spec_kind(Assembly(name="a")) == GROUP
    assert spec_kind(TableSpec(name="t")) == TABLE
    assert spec_kind(CabinetSpec(name="c")) == CABINET


def test_is_group_matches_componentgroup():
    assert is_group(Project()) and is_group(Assembly())
    assert not is_group(CabinetSpec(name="c"))
    assert not is_group(TableSpec(name="t"))


def test_new_group_subclass_flows_through_pipeline_unchanged():
    # A brand-new ComponentGroup subclass the stages have never heard of: it
    # must route as GROUP everywhere via spec_kind, with no stage edits.
    @dataclass
    class Wall(ComponentGroup):
        kind: str = "wall"

    wall = Wall(name="Feature Wall", components=[
        Component(spec=CabinetSpec(name="C1", width=600), x=0),
        Component(spec=CabinetSpec(name="C2", width=600), x=600),
    ])
    assert spec_kind(wall) == GROUP
    assert validate(wall).ok
    # Aggregates both cabinets' parts, just like a Project would.
    assert len(generate_cutlist(wall).parts) > 0
    assert estimate(wall).total > 0
    assert len(panel_layout(wall)) > 0


# Every pipeline-stage module that dispatches binds spec_kind by name at import,
# so a stage-free extensibility test must teach each binding about the new kind.
_DISPATCHERS = [
    "woodworking_ai.geometry", "woodworking_ai.cutlist",
    "woodworking_ai.validator", "woodworking_ai.joinery",
    "woodworking_ai.assembly_steps", "woodworking_ai.estimator",
    "woodworking_ai.drilling",
]


@dataclass
class WidgetSpec:
    name: str = "Widget"
    width: float = 400.0
    depth: float = 300.0
    height: float = 50.0


def test_new_leaf_type_flows_through_pipeline_without_stage_edits(monkeypatch):
    """A brand-new LEAF furniture type registered at test time must flow through
    panel_layout / validate / cutlist / joinery / assembly / estimate with no
    edit to any stage body — proving the H0 furniture registry (plus the single
    spec_kind dispatch) is the only thing a new type touches.
    """
    import importlib
    from woodworking_ai.cutlist import assign_ids

    KIND = "widget"
    original = dispatch.spec_kind

    def patched(spec):
        return KIND if isinstance(spec, WidgetSpec) else original(spec)

    # Patch the single dispatch source AND each stage's name-bound copy — no edit
    # to any stage *body*, only the one dispatch function each imports.
    monkeypatch.setattr(dispatch, "spec_kind", patched)
    for mod_name in _DISPATCHERS:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "spec_kind"):
            monkeypatch.setattr(mod, "spec_kind", patched, raising=False)

    saved = dict(furniture._REGISTRY)

    def widget_cutlist(s):
        cl = CutList(spec_name=s.name, parts=[Part(
            "Board", 1, length=s.width, width=s.depth, thickness=s.height,
            material="solid")])
        assign_ids(cl.parts)
        return cl

    try:
        furniture.register(
            KIND,
            panels=lambda s: [PanelBox(
                "Board", (s.width, s.depth, s.height), (0, s.depth / 2, 0),
                "top")],
            cut_parts=widget_cutlist,
            validate=lambda s: ([] if s.width > 0 else
                                [Issue("error", "width", "must be positive")]),
            joinery_ops=lambda s, cl: [JoineryOp(
                part="Board", operation="ease edges", tool="router",
                width=0.0, depth=0.0)],
            # no `assembly` → exercises the generic one-unit fallback
        )

        spec = WidgetSpec()
        assert dispatch.spec_kind(spec) == KIND

        panels = panel_layout(spec)
        assert len(panels) == 1 and panels[0].label == "Board"

        assert validate(spec).ok
        assert not validate(WidgetSpec(width=0.0)).ok

        cl = generate_cutlist(spec)
        assert len(cl.parts) == 1 and cl.parts[0].id

        sched = joinery_schedule(spec)
        assert sched.ops and sched.ops[0].operation == "ease edges"

        plan = assembly_plan(spec)
        assert plan.subassemblies                     # generic fallback plan
        assert estimate(spec).total > 0
    finally:
        furniture._REGISTRY.clear()
        furniture._REGISTRY.update(saved)
