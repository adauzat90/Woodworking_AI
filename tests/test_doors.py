"""Stile-and-rail (5-piece) doors and door styles."""

from woodworking_ai.dsl import CabinetSpec
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.joinery import joinery_schedule


def _cab(style="slab", doors=2):
    return CabinetSpec(width=800, height=720, depth=560, doors=doors, shelves=0,
                       door_style=style)


def test_slab_door_is_a_single_part():
    cl = generate_cutlist(_cab("slab"))
    door_parts = [p for p in cl.parts if p.material == "door/front"]
    assert any(p.name == "Door" for p in door_parts)
    assert not any("stile" in p.name.lower() for p in door_parts)


def test_shaker_door_breaks_into_five_pieces_per_leaf():
    cl = generate_cutlist(_cab("shaker", doors=2))
    stiles = next(p for p in cl.parts if p.name == "Door stile")
    rails = next(p for p in cl.parts if p.name == "Door rail")
    panels = next(p for p in cl.parts if p.name == "Door panel")
    assert stiles.qty == 4 and rails.qty == 4   # 2 each per leaf, 2 leaves
    assert panels.qty == 2


def test_panel_thinner_than_frame_and_floats():
    spec = _cab("shaker")
    cl = generate_cutlist(spec)
    panel = next(p for p in cl.parts if p.name == "Door panel")
    assert panel.thickness == spec.material.door_panel
    assert panel.thickness < spec.material.door


def test_panel_fits_inside_the_leaf():
    spec = _cab("shaker", doors=1)
    cl = generate_cutlist(spec)
    # The single door leaf spans roughly the opening; the panel is smaller.
    door_leaf_w = spec.width - 2 * spec.reveal
    panel = next(p for p in cl.parts if p.name == "Door panel")
    assert panel.width < door_leaf_w


def test_raised_panel_noted_solid():
    cl = generate_cutlist(_cab("raised_panel"))
    panel = next(p for p in cl.parts if p.name == "Door panel")
    assert "solid" in panel.notes.lower()


def test_five_piece_door_adds_cope_and_stick_joinery():
    ops = joinery_schedule(_cab("shaker")).ops
    assert any("cope-and-stick" in o.operation for o in ops)


def test_door_part_ids_are_in_the_front_series():
    cl = generate_cutlist(_cab("shaker"))
    for name in ("Door stile", "Door panel"):
        p = next(x for x in cl.parts if x.name == name)
        assert p.id.startswith("D")
