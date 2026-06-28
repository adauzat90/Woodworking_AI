"""Joinery/movement rules unblocked by the shelf-joint schema field (Tier 3 #9
unblocked subset): STRUCT-014 shelf-to-side attachment and MOVE-003 solid
frame-and-panel float gap.

The rest of the #9 batch (MOVE-005 cross-grain glue, GRAIN-002/004 per-part/per-
stave grain, MOVE-004 breadboard) stays blocked on a per-part grain model and a
breadboard feature; STRUCT-040/041 and GRAIN-003 are *moot* under today's DSL
(no open-back option; the cut list already auto-glues-up wide solids) and are
deliberately not emitted.
"""

from __future__ import annotations

from woodworking_ai import spec_from_dict, validate
from woodworking_ai.dsl import ShelfJoint
from woodworking_ai.joinery import joinery_schedule


def _cab(**kw):
    base = dict(kind="cabinet", cabinet_type="base", width=900, height=720,
                depth=560, shelves=2)
    base.update(kw)
    return spec_from_dict(base)


# --- schema: shelf_joint field --------------------------------------------

def test_shelf_joint_defaults_to_pins_and_coerces():
    assert _cab().shelf_joint == ShelfJoint.PINS
    assert _cab(shelf_joint="dado").shelf_joint == ShelfJoint.DADO
    # An unknown spelling degrades to a string rather than raising, so the spec
    # still loads (and the rule simply doesn't fire on it).
    assert _cab(shelf_joint="nonsense").shelf_joint == "nonsense"


def test_shelf_joint_round_trips_through_to_dict():
    assert _cab(shelf_joint="cleat").to_dict()["shelf_joint"] == "cleat"


# --- STRUCT-014 shelf-to-side joint ----------------------------------------

def test_struct014_flags_a_screwed_load_shelf():
    s = _cab(shelf_joint="screw")
    hits = validate(s).by_rule("STRUCT-014")
    assert len(hits) == 1
    assert hits[0].severity == "warning"
    assert "screw" in hits[0].message and hits[0].fix
    assert hits[0].doc_anchor.endswith("#32-joint-selection-by-load-strength-hierarchy")


def test_struct014_flags_a_butt_glued_load_shelf():
    assert len(validate(_cab(shelf_joint="butt")).by_rule("STRUCT-014")) == 1


def test_struct014_quiet_for_pins_dado_cleat():
    for j in ("pins", "dado", "cleat"):
        assert validate(_cab(shelf_joint=j)).by_rule("STRUCT-014") == [], j


def test_struct014_needs_a_shelf():
    # No shelves, no load shelf to mis-attach.
    assert validate(_cab(shelves=0, shelf_joint="screw")).by_rule("STRUCT-014") == []


def test_dado_shelf_emits_a_housing_op():
    ops = joinery_schedule(_cab(shelf_joint="dado")).ops
    assert any("dado for fixed shelf" == o.operation for o in ops)
    # A pin shelf (default) adds no housing op — keeps existing schedules stable.
    assert not any("shelf" in o.operation for o in joinery_schedule(_cab()).ops)


def test_cleat_shelf_emits_a_ledger_op():
    ops = joinery_schedule(_cab(shelf_joint="cleat")).ops
    assert any("cleat for fixed shelf" == o.operation for o in ops)


# --- MOVE-003 solid frame-and-panel float gap ------------------------------

def test_move003_flags_a_solid_raised_panel():
    hits = validate(_cab(doors=2, door_style="raised_panel")).by_rule("MOVE-003")
    assert len(hits) == 1
    assert hits[0].severity == "warning" and hits[0].fix
    assert hits[0].doc_anchor.endswith("#41-wood-movement-seasonal-expansioncontraction")


def test_move003_flags_a_solid_flat_panel():
    # A flat shaker panel made of solid wood moves just like a raised one.
    assert len(validate(_cab(doors=2, door_style="shaker",
                             material_form="solid")).by_rule("MOVE-003")) == 1


def test_move003_quiet_for_a_plywood_shaker_panel():
    # The default sheet-good flat panel doesn't move — no float gap needed.
    assert validate(_cab(doors=2, door_style="shaker")).by_rule("MOVE-003") == []


def test_move003_quiet_for_a_slab_door():
    assert validate(_cab(doors=2, door_style="slab")).by_rule("MOVE-003") == []


def test_move003_needs_a_door():
    assert validate(_cab(doors=0, door_style="raised_panel")).by_rule("MOVE-003") == []
