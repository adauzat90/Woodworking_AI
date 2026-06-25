"""Tests for drawer boxes and false fronts (pure math)."""

import pytest

from woodworking_ai import (
    CabinetSpec, Material, ToeKick, Drawer, generate_cutlist, estimate,
)


def spec(drawers, **o) -> CabinetSpec:
    d = dict(name="DB", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=0, doors=0, drawers=drawers, reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def test_drawer_emits_box_parts():
    cl = generate_cutlist(spec([Drawer(140)]))
    names = {p.name for p in cl.parts}
    assert "Drawer 1 box side" in names
    assert "Drawer 1 box front/back" in names
    assert "Drawer 1 box bottom" in names


def test_box_sides_and_frontback_are_pairs():
    cl = generate_cutlist(spec([Drawer(160)]))
    side = next(p for p in cl.parts if p.name == "Drawer 1 box side")
    fb = next(p for p in cl.parts if p.name == "Drawer 1 box front/back")
    assert side.qty == 2 and fb.qty == 2
    assert side.thickness == 12  # drawer_box stock


def test_box_width_accounts_for_slide_clearance():
    cl = generate_cutlist(spec([Drawer(140)], width=600))
    bottom = next(p for p in cl.parts if p.name == "Drawer 1 box bottom")
    # opening 600, minus 2 * 13mm slide clearance = 574
    assert bottom.length == pytest.approx(574)


def test_false_front_has_no_box_or_slides():
    cl = generate_cutlist(spec([Drawer(200, false_front=True)]))
    names = {p.name for p in cl.parts}
    assert "Drawer 1 box side" not in names
    assert not any(h.name == "Drawer slide (pair)" for h in cl.hardware)
    # The fixed front panel is still cut.
    assert any(p.name.startswith("Drawer front") for p in cl.parts)
    front = next(p for p in cl.parts if p.name.startswith("Drawer front"))
    assert "false front" in front.notes


def test_three_drawers_make_three_boxes():
    cl = generate_cutlist(spec([Drawer(140), Drawer(160), Drawer(180)]))
    sides = [p for p in cl.parts if "box side" in p.name]
    assert len(sides) == 3


def test_estimate_includes_drawer_box_material():
    est = estimate(spec([Drawer(140), Drawer(160)]))
    assert any(g.material == "drawer box" for g in est.groups)


def test_roundtrip_preserves_false_front():
    s = spec([Drawer(200, false_front=True)])
    assert CabinetSpec.from_json(s.to_json()).drawers[0].false_front is True


# --- C1: snap box depth to a real, orderable slide length -------------------

def test_box_depth_snaps_to_standard_slide():
    # 560mm deep, 6mm back -> interior 554, usable 529 -> longest fitting = 500.
    cl = generate_cutlist(spec([Drawer(140)], depth=560))
    side = next(p for p in cl.parts if p.name == "Drawer 1 box side")
    assert side.length == pytest.approx(500)
    assert "500mm slide" in side.notes


def test_chosen_slide_length_appears_in_hardware_bom():
    cl = generate_cutlist(spec([Drawer(140)], depth=560))
    slide = next(h for h in cl.hardware if h.name == "Drawer slide (pair)")
    assert "500" in slide.notes


def test_explicit_slide_length_is_respected():
    # An explicit slide length is not overridden by the snap logic.
    cl = generate_cutlist(spec([Drawer(140, slide_length=450)], depth=560))
    side = next(p for p in cl.parts if p.name == "Drawer 1 box side")
    # Box depth keeps the clearance-based size, not snapped to a standard slide.
    assert "slide" not in side.notes
    slide = next(h for h in cl.hardware if h.name == "Drawer slide (pair)")
    assert "450" in slide.notes
