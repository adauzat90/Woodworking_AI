"""Picture / mirror frame (G1) — four mitered rails with a glazing rabbet.

Proves the frame leaf type flows through the whole pipeline (dispatch, validate,
cut list, geometry, joinery, assembly, estimate) and into a Project, with no edit
to any generic stage — the leaf-furniture path holds for a fifth home-shop type.
"""

import pytest

from woodworking_ai import (
    FrameSpec, FrameJoint, FrameHanger, FrameContents,
    Project, Component, validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, FRAME
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai import furniture


def _frame(**kw) -> FrameSpec:
    base = dict(name="Walnut Frame", opening_w=400, opening_h=500,
                molding_width=40, molding_thickness=20, species="walnut")
    base.update(kw)
    return FrameSpec(**base)


def test_dispatch_kind_and_registry():
    assert spec_kind(_frame()) == FRAME
    assert furniture.is_registered(FRAME)


def test_spec_from_dict_routes_frame():
    spec = spec_from_dict({"kind": "frame", "opening_w": 300, "opening_h": 400})
    assert isinstance(spec, FrameSpec)
    assert spec_kind(spec) == FRAME


def test_roundtrip_to_from_dict_preserves_enums():
    spec = _frame(corner_joint="half_lap", contents="mirror", hanger="cleat",
                  glazing="none")
    again = FrameSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.corner_joint == FrameJoint.HALF_LAP
    assert again.contents == FrameContents.MIRROR
    assert again.hanger == FrameHanger.CLEAT


def test_imperial_on_load_converts_to_mm():
    spec = FrameSpec.from_dict(
        {"units": "in", "opening_w": 16, "opening_h": 20, "molding_width": 1.5,
         "molding_thickness": 0.75, "rabbet_width": 0.375, "rabbet_depth": 0.5})
    assert spec.units == "mm"
    assert spec.opening_w == pytest.approx(16 * MM_PER_IN)
    assert spec.molding_width == pytest.approx(1.5 * MM_PER_IN)
    assert spec.rabbet_depth == pytest.approx(0.5 * MM_PER_IN)


def test_outer_and_glazing_geometry():
    spec = _frame(opening_w=400, opening_h=500, molding_width=40, rabbet_width=8)
    assert spec.outer_w == pytest.approx(480)   # 400 + 2*40
    assert spec.outer_h == pytest.approx(580)
    assert spec.glazing_w == pytest.approx(416)  # 400 + 2*8
    assert spec.glazing_h == pytest.approx(516)
    # Placement aliases let a frame sit inside a Project like any leaf.
    assert spec.width == spec.outer_w and spec.height == spec.outer_h
    assert spec.depth == spec.molding_thickness


def test_four_rails_tile_the_face_without_overlap():
    panels = panel_layout(_frame())
    labels = [p.label for p in panels]
    assert labels == ["Rail top", "Rail bottom", "Rail left", "Rail right"]
    # The four rails should never be glazing — no non-wood part sneaks into panels.
    assert all(p.label.startswith("Rail") for p in panels)


def test_cutlist_rails_and_glazing_and_hanger():
    cl = generate_cutlist(_frame())
    names = [p.name for p in cl.parts]
    assert "Rail (top/bottom)" in names and "Rail (side)" in names
    assert all(p.id for p in cl.parts)
    hw = " ".join(h.name.lower() for h in cl.hardware)
    assert "glazing" in hw and "backer" in hw      # default art frame is glazed
    assert "d-ring" in hw and "wire" in hw          # default hanger


def test_splined_miter_adds_corner_splines():
    cl = generate_cutlist(_frame(corner_joint="splined_miter"))
    assert any("spline" in h.name.lower() for h in cl.hardware)


def test_mirror_uses_mirror_not_glass_and_no_backer_glazing_line():
    cl = generate_cutlist(_frame(contents="mirror", glazing="none"))
    hw = [h.name.lower() for h in cl.hardware]
    assert any("mirror" in h for h in hw)
    assert not any("glazing (glass" in h for h in hw)


def test_open_frame_has_no_glazing_or_retainers():
    cl = generate_cutlist(_frame(contents="none", glazing="none"))
    hw = [h.name.lower() for h in cl.hardware]
    assert not any("glazing" in h or "backer" in h or "glazier" in h for h in hw)


def test_hanger_variants():
    saw = generate_cutlist(_frame(hanger="sawtooth"))
    assert any("sawtooth" in h.name.lower() for h in saw.hardware)
    cleat = generate_cutlist(_frame(hanger="cleat"))
    assert any("cleat" in h.name.lower() for h in cleat.hardware)


def test_validate_sane_frame_passes():
    assert validate(_frame()).ok


def test_validate_rejects_nonpositive_dims():
    assert not validate(_frame(opening_w=0)).ok


def test_validate_rejects_rabbet_deeper_than_molding():
    res = validate(_frame(molding_thickness=10, rabbet_depth=12))
    assert not res.ok
    assert any(i.field == "rabbet_depth" for i in res.issues if i.severity == "error")


def test_validate_rejects_rabbet_wider_than_face():
    res = validate(_frame(molding_width=20, rabbet_width=22))
    assert not res.ok
    assert any(i.field == "rabbet_width" for i in res.issues if i.severity == "error")


def test_validate_warns_on_plain_miter():
    res = validate(_frame(corner_joint="miter"))
    assert any(i.field == "corner_joint" for i in res.warnings)


def test_validate_warns_on_heavy_mirror_with_sawtooth():
    res = validate(_frame(contents="mirror", hanger="sawtooth"))
    assert any(i.field == "hanger" for i in res.warnings)


def test_validate_strong_joints_pass_clean_on_corner():
    for cj in ("splined_miter", "half_lap", "cope_stick"):
        res = validate(_frame(corner_joint=cj))
        assert not any(i.field == "corner_joint" for i in res.warnings), cj


def test_joinery_has_corner_and_rabbet_ops():
    ops = joinery_schedule(_frame()).ops
    operations = " ".join(o.operation for o in ops).lower()
    assert "miter" in operations          # default splined miter
    assert "rabbet" in operations         # glazing rabbet
    # Every corner-joint choice still produces a buildable schedule.
    for cj in ("miter", "splined_miter", "half_lap", "cope_stick"):
        assert joinery_schedule(_frame(corner_joint=cj)).ops


def test_assembly_plan_phases():
    plan = assembly_plan(_frame())
    names = [s.name for s in plan.subassemblies]
    assert "Frame" in names
    assert "Glazing & backer" in names
    assert "Finish & hang" in names


def test_estimate_prices_the_frame():
    assert estimate(_frame()).total > 0


def test_frame_inside_a_project():
    proj = Project(name="Gallery wall", components=[
        Component(spec=_frame(name="A", opening_w=300, opening_h=400),
                  x=0, label="A"),
        Component(spec=_frame(name="B", opening_w=300, opening_h=400),
                  x=700, label="B"),
    ])
    assert validate(proj).ok
    assert len(generate_cutlist(proj).parts) >= 4
    assert estimate(proj).total > 0
