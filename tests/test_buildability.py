"""Critic buildability checks: machinability, door swing, FF slide stack-up."""

from woodworking_ai.dsl import CabinetSpec, Drawer, Material, Construction
from woodworking_ai.agents.critic import critique


def _cab(**kw):
    base = dict(width=600, height=720, depth=560, doors=2, shelves=1)
    base.update(kw)
    return CabinetSpec(**base)


def test_normal_cabinet_has_no_buildability_warnings():
    crit = critique(_cab())
    assert crit.ok
    assert not any(w.kind in ("machinability", "clearance") for w in crit.warnings)


def test_thick_panel_dado_flagged_as_unmachinable():
    # A 30mm carcass is past the dado stack and matches no router bit on hand.
    crit = critique(_cab(material=Material(carcass=30.0)))
    assert any(w.kind == "machinability" for w in crit.warnings)


def test_deep_box_flags_drill_reach():
    crit = critique(_cab(depth=700, shelves=2))
    assert any("hand-drill reach" in w.message for w in crit.warnings)


def test_inset_twin_doors_without_mullion_warn():
    crit = critique(_cab(construction=Construction.FACE_FRAME, doors=2,
                         center_mullion=False))
    assert any(w.kind == "clearance" and "inset twin doors" in w.message
               for w in crit.warnings)


def test_inset_twin_doors_with_mullion_ok():
    crit = critique(_cab(construction=Construction.FACE_FRAME, doors=2,
                         center_mullion=True))
    assert not any("inset twin doors" in w.message for w in crit.warnings)


def test_face_frame_sidemount_drawer_needs_buildout():
    crit = critique(_cab(construction=Construction.FACE_FRAME, doors=0,
                         drawers=[Drawer(front_height=150, slide_type="side_mount")]))
    assert any("build-out" in w.message for w in crit.warnings)


def test_frameless_drawer_has_no_buildout_warning():
    crit = critique(_cab(doors=0,
                         drawers=[Drawer(front_height=150, slide_type="side_mount")]))
    assert not any("build-out" in w.message for w in crit.warnings)
