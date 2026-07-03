"""Tests for drawer boxes and false fronts (pure math)."""

import pytest

from woodworking_ai import (
    CabinetSpec, Material, ToeKick, Drawer, generate_cutlist, estimate,
    validate,
)
from woodworking_ai.drilling import drilling_schedule
from woodworking_ai.geometry import panel_layout
from woodworking_ai.constants import HOUSED_DEPTH_FRACTION


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
    # opening 600, minus 2 * 12.7mm (½in) side-mount slide clearance = 574.6
    assert bottom.length == pytest.approx(574.6)


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


# --- Wooden runners on a cabinet drawer (slide_type="wood"/"none") ----------

def test_wood_runner_emits_runner_parts_and_no_metal_slide():
    cl = generate_cutlist(spec([Drawer(180, slide_type="wood")]))
    runners = [p for p in cl.parts if p.name == "Drawer 1 wood runner"]
    assert len(runners) == 1 and runners[0].qty == 2   # one L + R pair
    assert runners[0].grain == "length"                # solid lumber strip
    # No metal slide or locking hardware for a wood-runner drawer.
    assert not any(h.name == "Drawer slide (pair)" for h in cl.hardware)
    assert not any("locking device" in h.name for h in cl.hardware)
    # The pull is still specified.
    assert any(h.name == "Drawer pull" for h in cl.hardware)


def test_wood_runner_box_is_grooved_not_slide_sized():
    cl = generate_cutlist(spec([Drawer(180, slide_type="wood")], depth=560))
    side = next(p for p in cl.parts if p.name == "Drawer 1 box side")
    # A slideless box runs the full interior depth; it is not snapped to a
    # standard metal-slide length, and its note mentions the runner groove.
    assert "slide" not in side.notes
    assert "runner" in side.notes


def test_none_slide_has_no_runner_part_and_no_slide():
    cl = generate_cutlist(spec([Drawer(180, slide_type="none")]))
    assert not any(p.name == "Drawer 1 wood runner" for p in cl.parts)
    assert not any(h.name == "Drawer slide (pair)" for h in cl.hardware)
    # It is still a real drawer with a box.
    assert any(p.name == "Drawer 1 box side" for p in cl.parts)


def test_wood_runner_drilling_has_runner_screws_not_slide_lines():
    sched = drilling_schedule(spec([Drawer(180, slide_type="wood")]))
    ops = {o.operation for o in sched.ops}
    assert any("wood runner screws" in o for o in ops)
    assert not any("slide line" in o for o in ops)
    assert not any("undermount slide" in o for o in ops)


def test_none_slide_drilling_has_no_slide_or_runner_ops():
    sched = drilling_schedule(spec([Drawer(180, slide_type="none")]))
    ops = {o.operation for o in sched.ops}
    assert not any("slide" in o or "runner" in o for o in ops)


def test_wood_runner_cabinet_validates():
    result = validate(spec([Drawer(170, slide_type="wood"),
                            Drawer(240, slide_type="wood")]))
    assert result.ok, [str(i) for i in result.issues]


def test_wood_runner_alias_normalizes():
    # Friendly aliases coerce to the canonical slide types.
    assert Drawer(180, slide_type="wooden").slide_type.value == "wood"
    assert Drawer(180, slide_type="runners").slide_type.value == "wood"
    assert Drawer(180, slide_type="web_frame").slide_type.value == "none"


# --- Geometry: the captured bottom + mirrored-side housing face ---------------

def _panels(drawers, **o):
    return {p.label: p for p in panel_layout(spec(drawers, **o))}


def test_box_bottom_geometry_extends_into_side_grooves():
    # The 3D bottom must run WIDER than the clear interior (box_w - 2t) — into
    # both side grooves — so it seats in the groove instead of floating short.
    t = 12.0
    ps = _panels([Drawer(180)])
    side = ps["Drawer 1 box side L"]
    bottom = ps["Drawer 1 box bottom"]
    box_w = side and None  # box_w isn't exposed; derive from the two side centres
    xl = ps["Drawer 1 box side L"].center[0]
    xr = ps["Drawer 1 box side R"].center[0]
    box_w = (xr - xl) + t                      # sides are inset t/2 from the walls
    gd = t * HOUSED_DEPTH_FRACTION
    assert bottom.size[0] == pytest.approx(box_w - 2 * t + 2 * gd)  # into grooves
    assert bottom.size[0] > box_w - 2 * t                          # wider than clear


def test_mirrored_right_side_cuts_from_inner_face():
    # A right-hand panel's inner face points -X, so its housings/bores must be
    # cut from the -normal face (inner_sign = -1), not the outside.
    ps = _panels([Drawer(180)])
    assert ps["Drawer 1 box side L"].inner_sign == 1.0
    assert ps["Drawer 1 box side R"].inner_sign == -1.0
    assert ps["Side L"].inner_sign == 1.0
    assert ps["Side R"].inner_sign == -1.0


def test_carcass_bottom_seats_into_side_dados():
    # With a dado carcass the bottom runs into both side dados (interior + 2×9mm)
    # and carries capture_grow so the interference check ignores that seating.
    ps = _panels([Drawer(180)], joinery="dado")
    bottom = ps["Bottom"]
    interior_w = 600 - 2 * 18
    assert bottom.size[0] == pytest.approx(interior_w + 2 * (18 * HOUSED_DEPTH_FRACTION))
    assert bottom.capture_grow[0] == pytest.approx(18 * HOUSED_DEPTH_FRACTION)


def test_butt_carcass_bottom_stays_clear_interior():
    # A non-housed (screw/butt) carcass has no slot, so the bottom is NOT grown.
    ps = _panels([Drawer(180)], joinery="screw")
    bottom = ps["Bottom"]
    assert bottom.size[0] == pytest.approx(600 - 2 * 18)
    assert bottom.capture_grow[0] == 0.0


def test_project_layout_propagates_machining_hints():
    # A run re-creates each PanelBox; it MUST carry inner_sign + capture_grow
    # through, or every project silently loses its mirrored-side grooves and
    # captured bottoms (the bug that shipped a right-side dado on the outside).
    from woodworking_ai import Project, place_run
    from woodworking_ai.geometry import panel_layout
    banks = [spec([Drawer(180)], name="A", joinery="dado"),
             spec([Drawer(180)], name="B", joinery="dado")]
    proj = Project(components=place_run(banks, start=(0, 0), angle=0))
    ps = {p.label: p for p in panel_layout(proj)}
    side_r = next(p for lbl, p in ps.items() if lbl.endswith("Side R"))
    bottom = next(p for lbl, p in ps.items() if lbl.endswith("Bottom"))
    assert side_r.inner_sign == -1.0
    assert bottom.capture_grow[0] > 0.0
