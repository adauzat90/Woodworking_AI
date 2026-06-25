"""Assembly sequence: ordered, complete, drilling-before-glue-up."""

from woodworking_ai.dsl import (CabinetSpec, TableSpec, Drawer, Project,
                                Component, Construction)
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.assembly_steps import assembly_sequence


def _cab(**kw):
    base = dict(width=600, height=720, depth=560, shelves=1, doors=2,
                drawers=[Drawer(front_height=140)])
    base.update(kw)
    return CabinetSpec(**base)


def test_steps_are_numbered_in_order():
    seq = assembly_sequence(_cab())
    nums = [s.number for s in seq.steps]
    assert nums == list(range(1, len(nums) + 1))


def test_drilling_precedes_carcass_glue_up():
    seq = assembly_sequence(_cab())
    drill = next(i for i, s in enumerate(seq.steps) if "Drill" in s.title)
    glue = next(i for i, s in enumerate(seq.steps) if "carcass" in s.title.lower())
    assert drill < glue, "drill flat panels before assembling the carcass"


def test_every_part_is_referenced_in_some_step():
    spec = _cab()
    ids = {p.id for p in generate_cutlist(spec).parts if p.id}
    seq = assembly_sequence(spec)
    referenced = {pid for s in seq.steps for pid in s.part_ids}
    assert ids <= referenced, "every cut-list part must appear in a step"


def test_fronts_come_after_the_carcass():
    seq = assembly_sequence(_cab())
    glue = next(i for i, s in enumerate(seq.steps) if "carcass" in s.title.lower())
    doors = next(i for i, s in enumerate(seq.steps) if "Hang the doors" in s.title)
    assert doors > glue


def test_finish_is_last():
    seq = assembly_sequence(_cab())
    assert seq.steps[-1].category == "finish"


def test_table_sequence_attaches_top_with_movement():
    seq = assembly_sequence(TableSpec())
    top_step = next(s for s in seq.steps if "top" in s.title.lower())
    assert "movement" in top_step.detail.lower()


def test_project_sequence_ends_with_install_and_namespaces_ids():
    proj = Project(name="Run", components=[
        Component(spec=_cab(), label="B1"),
        Component(spec=_cab(), label="B2"),
    ])
    seq = assembly_sequence(proj)
    assert seq.steps[-1].category == "install"
    ids = {pid for s in seq.steps for pid in s.part_ids}
    assert any(i.startswith("B1-") for i in ids)
