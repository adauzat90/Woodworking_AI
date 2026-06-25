"""Stable part identity: cut-list IDs, cross-referenced by drilling and nests."""

from woodworking_ai.dsl import CabinetSpec, Drawer, Project, Component
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.drilling import drilling_schedule


def _cab() -> CabinetSpec:
    return CabinetSpec(width=600, height=720, depth=560, shelves=2, doors=2,
                       drawers=[Drawer(front_height=140)])


def test_every_part_gets_an_id():
    cl = generate_cutlist(_cab())
    assert all(p.id for p in cl.parts), "every part must have an ID"


def test_ids_are_unique_and_deterministic():
    a = generate_cutlist(_cab())
    b = generate_cutlist(_cab())
    ids_a = [p.id for p in a.parts]
    assert len(ids_a) == len(set(ids_a)), "IDs must be unique within a cut list"
    assert ids_a == [p.id for p in b.parts], "IDs must be deterministic"


def test_ids_grouped_by_category_prefix():
    cl = generate_cutlist(_cab())
    by_name = {p.name: p.id for p in cl.parts}
    # Carcass sides are the 'A' series; doors are the 'D' series.
    assert by_name["Side"].startswith("A")
    assert by_name["Door"].startswith("D")
    assert by_name["Back"].startswith("B")
    assert by_name["Adjustable shelf"].startswith("C")


def test_drilling_ops_reference_cutlist_ids():
    spec = _cab()
    cl = generate_cutlist(spec)
    valid_ids = {p.id for p in cl.parts}
    sched = drilling_schedule(spec)
    resolved = [op for op in sched.ops if op.part_id]
    assert resolved, "at least some drill ops should resolve to a part ID"
    for op in resolved:
        assert op.part_id in valid_ids, f"{op.part!r} -> unknown id {op.part_id!r}"


def test_project_ids_are_namespaced_per_component():
    proj = Project(name="Run", components=[
        Component(spec=_cab(), x=0, y=0, label="B1"),
        Component(spec=_cab(), x=600, y=0, label="B2"),
    ])
    cl = generate_cutlist(proj)
    ids = [p.id for p in cl.parts]
    assert len(ids) == len(set(ids)), "project part IDs must stay unique"
    assert any(i.startswith("B1-") for i in ids)
    assert any(i.startswith("B2-") for i in ids)
