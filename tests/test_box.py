"""Box / chest (H1) — a six-board box with a selectable corner joint + lid.

Proves the box leaf type flows through the whole pipeline and reuses the
drawer-box CornerJoint vocabulary, with no edit to any generic stage.
"""

import pytest

from woodworking_ai import (
    BoxSpec, CornerJoint, Project, Component,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, BOX
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai import furniture


def _box(**kw) -> BoxSpec:
    base = dict(name="Walnut Chest", width=600, depth=400, height=350,
                thickness=18, species="walnut")
    base.update(kw)
    return BoxSpec(**base)


def test_dispatch_kind_and_registry():
    assert spec_kind(_box()) == BOX
    assert furniture.is_registered(BOX)


def test_spec_from_dict_routes_box_and_chest_alias():
    assert isinstance(spec_from_dict({"kind": "box", "width": 500}), BoxSpec)
    assert isinstance(spec_from_dict({"kind": "chest", "width": 500}), BoxSpec)


def test_roundtrip_to_from_dict():
    spec = _box(corner_joint="box", lid=False)
    again = BoxSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.corner_joint == CornerJoint.BOX


def test_imperial_on_load_converts_to_mm():
    spec = BoxSpec.from_dict(
        {"units": "in", "width": 24, "depth": 16, "height": 14, "thickness": 0.75})
    assert spec.units == "mm"
    assert spec.width == pytest.approx(24 * MM_PER_IN)
    assert spec.thickness == pytest.approx(0.75 * MM_PER_IN)


def test_six_board_panels_with_lid():
    panels = panel_layout(_box())
    labels = [p.label for p in panels]
    for expected in ("Bottom", "Front", "Back", "Side L", "Side R", "Lid"):
        assert expected in labels


def test_open_box_has_no_lid_panel():
    panels = panel_layout(_box(lid=False))
    assert "Lid" not in [p.label for p in panels]


def test_cutlist_parts_and_lid_hinges():
    cl = generate_cutlist(_box())
    names = [p.name for p in cl.parts]
    assert "Front/back" in names and "Side" in names and "Bottom" in names
    assert "Lid" in names
    assert all(p.id for p in cl.parts)
    hw = [h.name.lower() for h in cl.hardware]
    assert any("hinge" in h for h in hw)


def test_open_box_has_no_hinges():
    cl = generate_cutlist(_box(lid=False))
    assert "Lid" not in [p.name for p in cl.parts]
    assert not any("hinge" in h.name.lower() for h in cl.hardware)


def test_corner_joint_reuses_drawer_vocabulary():
    for cj in ("dovetail", "box", "locking_rabbet", "rabbet", "butt"):
        spec = _box(corner_joint=cj)
        assert spec.corner_joint == CornerJoint(cj)
        # Cut list + joinery must build for every corner joint.
        assert generate_cutlist(spec).parts
        assert joinery_schedule(spec).ops


def test_validate_sane_box_passes():
    assert validate(_box()).ok


def test_validate_rejects_nonpositive_dims():
    assert not validate(_box(width=0)).ok


def test_validate_warns_on_butt_corners():
    res = validate(_box(corner_joint="butt"))
    assert any("corner" in i.field for i in res.warnings)


def test_validate_rejects_too_thick_walls():
    assert not validate(_box(width=30, depth=30, thickness=18)).ok


def test_joinery_has_corners_and_bottom_groove():
    ops = joinery_schedule(_box()).ops
    operations = " ".join(o.operation for o in ops).lower()
    assert "corner" in operations
    assert "groove for bottom" in operations
    assert "hinge" in operations             # lid hinge mortise


def test_assembly_plan_has_body_and_lid():
    plan = assembly_plan(_box())
    names = [s.name for s in plan.subassemblies]
    assert "Box body" in names
    assert "Lid" in names


def test_estimate_prices_the_box():
    assert estimate(_box()).total > 0


def test_box_inside_a_project():
    proj = Project(name="Chests", components=[
        Component(spec=_box(name="A", width=500), x=0, label="A"),
        Component(spec=_box(name="B", width=500), x=1000, label="B"),
    ])
    assert validate(proj).ok
    assert len(generate_cutlist(proj).parts) >= 8
    assert estimate(proj).total > 0
