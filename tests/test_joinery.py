"""Joinery setup sheet: machining dimensions keyed to part IDs."""

from woodworking_ai.dsl import (TableSpec, Drawer, BackStyle,
                                Joinery, Project, Component)
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.joinery import joinery_schedule
from factories import cab_with_drawer as _cab


def test_dado_cut_to_mating_thickness_and_half_depth():
    spec = _cab(joinery=Joinery.DADO)
    ops = joinery_schedule(spec).ops
    bottom = next(o for o in ops if o.operation == "joint for bottom")
    assert bottom.width == spec.material.carcass          # snug to the panel
    assert bottom.depth == round(spec.material.carcass * 0.5, 1)
    assert "dado" in bottom.tool.lower()


def test_rabbeted_back_emits_a_rabbet_op():
    spec = _cab(back=BackStyle.RABBETED)
    ops = joinery_schedule(spec).ops
    assert any(o.operation == "rabbet for back" for o in ops)


def test_grooved_back_emits_a_groove_inset_from_rear():
    spec = _cab(back=BackStyle.GROOVED)
    op = next(o for o in joinery_schedule(spec).ops
              if o.operation == "groove for back")
    assert "from the rear" in op.reference


def test_applied_back_has_no_back_machining():
    spec = _cab(back=BackStyle.APPLIED)
    ops = joinery_schedule(spec).ops
    assert not any("back" in o.operation for o in ops)


def test_dovetail_drawer_notes_tails_on_sides():
    spec = _cab(doors=0, drawers=[Drawer(front_height=150, corner_joint="dovetail")])
    op = next(o for o in joinery_schedule(spec).ops if "dovetail" in o.operation)
    assert "tails on the sides" in op.note


def test_ops_reference_valid_part_ids():
    spec = _cab()
    valid = {p.id for p in generate_cutlist(spec).parts}
    ops = [o for o in joinery_schedule(spec).ops if o.part_id]
    assert ops
    for o in ops:
        assert o.part_id in valid


def test_table_leg_apron_joint():
    t = TableSpec(joinery="mortise_tenon")
    op = next(o for o in joinery_schedule(t).ops if "leg-to-apron" in o.operation)
    assert "M&T" in op.note or "mortis" in op.tool.lower()


def test_project_namespaces_joinery_part_ids():
    proj = Project(name="Run", components=[
        Component(spec=_cab(), label="B1"),
        Component(spec=_cab(), label="B2"),
    ])
    ids = {o.part_id for o in joinery_schedule(proj).ops if o.part_id}
    assert any(i.startswith("B1-") for i in ids)
    assert any(i.startswith("B2-") for i in ids)
