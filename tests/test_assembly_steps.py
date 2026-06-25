"""Assembly sequence: ordered, complete, drilling-before-glue-up."""

from woodworking_ai.dsl import (CabinetSpec, TableSpec, Drawer, Project,
                                Component, Construction)
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.assembly_steps import assembly_sequence, assembly_plan


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
    top_step = next(s for s in seq.steps if "attach the top" in s.title.lower())
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


# --- hierarchical plan: sub-assemblies, each with their own steps ---------

def _names(plan):
    return [s.name for s in plan.subassemblies]


def test_plan_breaks_into_named_subassemblies():
    plan = assembly_plan(_cab(drawers=[Drawer(140), Drawer(160)]))
    names = _names(plan)
    assert "Carcass" in names
    assert "Drawer box 1" in names and "Drawer box 2" in names
    assert names[0] == "Preparation"
    assert names[-1] == "Final assembly"


def test_each_subassembly_has_its_own_steps():
    plan = assembly_plan(_cab())
    for sub in plan.subassemblies:
        assert sub.steps, f"{sub.name} should have build steps"
        assert sub.steps[0].number == 1   # steps numbered within the unit


def test_five_piece_door_gets_a_door_subassembly():
    plan = assembly_plan(_cab(door_style="shaker", doors=2))
    names = _names(plan)
    assert any(n.startswith("Door") for n in names)


def test_slab_door_has_no_door_subassembly():
    plan = assembly_plan(_cab(door_style="slab", doors=2))
    assert not any(s.name.startswith("Door") for s in plan.subassemblies)


def test_face_frame_is_its_own_subassembly():
    plan = assembly_plan(_cab(construction=Construction.FACE_FRAME))
    assert "Face frame" in _names(plan)


def test_flat_sequence_matches_the_plan():
    spec = _cab(drawers=[Drawer(140)])
    plan = assembly_plan(spec)
    flat = assembly_sequence(spec).steps
    assert len(flat) == sum(len(s.steps) for s in plan.subassemblies)
    assert [s.number for s in flat] == list(range(1, len(flat) + 1))


def test_drawer_box_subassembly_owns_only_its_parts():
    spec = _cab(doors=0, drawers=[Drawer(140), Drawer(160)])
    cl = generate_cutlist(spec)
    plan = assembly_plan(spec)
    box1 = next(s for s in plan.subassemblies if s.name == "Drawer box 1")
    # Its part IDs are the box-1 parts, not box-2's.
    box1_ids = {p.id for p in cl.parts if "drawer 1 box" in p.name.lower()}
    assert set(box1.part_ids) == box1_ids


def test_project_plan_namespaces_and_ends_with_run_install():
    proj = Project(name="Run", components=[
        Component(spec=_cab(), label="B1"),
        Component(spec=_cab(), label="B2"),
    ])
    plan = assembly_plan(proj)
    assert plan.subassemblies[-1].name == "Set & join the run"
    assert any(s.name.startswith("[B1]") for s in plan.subassemblies)


def test_carcass_excludes_drawer_box_and_accessory_parts():
    # Regression: loose substring matching used to pull "box side" and
    # "countertop" into the carcass. Each part must live in exactly one unit.
    spec = _cab(door_style="shaker", drawers=[Drawer(140)],
                accessories=[{"kind": "countertop", "depth": 600},
                             {"kind": "end_panel", "side": "right"}])
    cl = generate_cutlist(spec)
    by_id = {p.id: p.name.lower() for p in cl.parts}
    plan = assembly_plan(spec)
    carcass = next(s for s in plan.subassemblies if s.name == "Carcass")
    for pid in carcass.part_ids:
        n = by_id[pid]
        assert "box" not in n and "countertop" not in n and "door" not in n, n


def test_drawer_box_section_holds_only_box_parts():
    spec = _cab(doors=0, drawers=[Drawer(140)])
    cl = generate_cutlist(spec)
    by_id = {p.id: p.name.lower() for p in cl.parts}
    plan = assembly_plan(spec)
    box = next(s for s in plan.subassemblies if s.name == "Drawer box 1")
    assert all("box" in by_id[pid] for pid in box.part_ids)


# --- H4: glue-up / clamping checklist -------------------------------------

from woodworking_ai.assembly_steps import clamp_plan


def _titles(sub):
    return [s.title.lower() for s in sub.steps]


def test_clamp_plan_scales_with_glue_line_and_span():
    # more glue line -> more clamps; longer span -> longer clamps
    short = clamp_plan(300, 400)
    longer = clamp_plan(900, 400)
    assert longer["count"] > short["count"]
    assert clamp_plan(300, 800)["length_mm"] > clamp_plan(300, 400)["length_mm"]
    # a degenerate glue-up asks for no clamps
    assert clamp_plan(0, 0)["count"] == 0


def test_carcass_glue_up_gains_dry_fit_and_clamp_schedule():
    plan = assembly_plan(_cab())
    carc = next(s for s in plan.subassemblies if s.name == "Carcass")
    titles = _titles(carc)
    assert any("dry-fit" in t for t in titles), "a glued unit needs a dry-fit"
    assert any("diagonal" in t for t in titles), "check diagonals for square"
    assert any("open-time" in t for t in titles), "PVA open-time caution"
    clamp = next(s for s in carc.steps if "clamp schedule" in s.title.lower())
    # the clamp step names a real count and nominal length
    assert "clamps" in clamp.detail.lower()
    assert "mm" in clamp.detail
    assert "Bar/parallel clamps" in clamp.hardware


def test_open_time_caution_mentions_pva_minutes():
    plan = assembly_plan(_cab())
    carc = next(s for s in plan.subassemblies if s.name == "Carcass")
    cau = next(s for s in carc.steps if "open-time" in s.title.lower())
    assert "5-10" in cau.detail or "5" in cau.detail


def test_drawer_box_glue_up_gets_clamp_schedule():
    plan = assembly_plan(_cab(doors=0, drawers=[Drawer(140)]))
    box = next(s for s in plan.subassemblies if s.name == "Drawer box 1")
    assert any("clamp schedule" in t for t in _titles(box))
    assert any("dry-fit" in t for t in _titles(box))


def test_door_leaf_glue_up_warns_about_floating_panel():
    plan = assembly_plan(_cab(door_style="shaker", doors=2))
    door = next(s for s in plan.subassemblies if s.name.startswith("Door"))
    blob = " ".join(s.detail.lower() for s in door.steps)
    assert "floating" in blob, "frame-and-panel leaf must leave the panel floating"


def test_solid_table_top_warns_cross_grain():
    seq = assembly_plan(TableSpec(species="oak", material_form="solid"))
    top = next(s for s in seq.subassemblies if s.name == "Top")
    blob = " ".join(s.detail.lower() for s in top.steps)
    assert "cross-grain" in blob or "cross grain" in blob
    assert any("clamp schedule" in t for t in _titles(top))


def test_augmented_steps_stay_numbered_in_order():
    # adding glue-up steps must not break the per-unit 1..N numbering
    plan = assembly_plan(_cab())
    for sub in plan.subassemblies:
        nums = [s.number for s in sub.steps]
        assert nums == list(range(1, len(nums) + 1))


def test_existing_carcass_glue_step_is_preserved():
    # augmentation is additive: the original glue & clamp step still exists
    plan = assembly_plan(_cab())
    carc = next(s for s in plan.subassemblies if s.name == "Carcass")
    assert any("glue & clamp the carcass" in t for t in _titles(carc))
