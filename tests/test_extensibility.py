"""Guard the spec-type dispatch unification (Phase 8).

The pipeline's type ladder (ApplianceVoid -> ComponentGroup -> TableSpec ->
cabinet) is now defined once in ``dispatch.spec_kind``; every stage routes
through it instead of re-implementing isinstance checks. These tests pin that
single source down and prove a new ComponentGroup subclass flows through the
whole pipeline without editing any stage.
"""

from dataclasses import dataclass

from woodworking_ai import (
    CabinetSpec, TableSpec, Component, Project, Assembly,
    validate, generate_cutlist, estimate,
)
from woodworking_ai.dsl import ApplianceVoid, ComponentGroup
from woodworking_ai.dispatch import spec_kind, is_group, VOID, GROUP, TABLE, CABINET
from woodworking_ai.geometry import panel_layout


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
