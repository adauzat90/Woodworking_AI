"""Building / barndominium frame — auto-placed carrying beams + support posts.

Proves the building leaf type flows through the whole pipeline (dispatch, load,
geometry, cut list, validate, joinery, assembly, estimate) with no edit to any
generic stage, and that the auto-placer sizes the post layout to the safe span.
"""

import pytest

from woodworking_ai import (
    BuildingFrameSpec, BeamMaterial, SpanDirection,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, BUILDING
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai.building import frame_plan
from woodworking_ai import furniture, engineering


def _b(**kw) -> BuildingFrameSpec:
    base = dict(name="Barndo", length=12192, width=9144, wall_height=3658)
    base.update(kw)
    return BuildingFrameSpec(**base)


# --- taxonomy / loading -----------------------------------------------------

def test_dispatch_kind_and_registry():
    assert spec_kind(_b()) == BUILDING
    assert furniture.is_registered(BUILDING)


def test_spec_from_dict_routes_building_and_aliases():
    for kind in ("building", "barndominium", "building_frame"):
        spec = spec_from_dict({"kind": kind, "length": 12000, "width": 9000})
        assert isinstance(spec, BuildingFrameSpec), kind
        assert spec_kind(spec) == BUILDING


def test_roundtrip_to_from_dict():
    spec = _b(beam_material="lvl", span_direction="width", post_size=160)
    again = BuildingFrameSpec.from_dict(spec.to_dict())
    assert again.beam_material is BeamMaterial.LVL
    assert again.span_direction is SpanDirection.WIDTH
    assert again.post_size == 160


def test_imperial_input_converts_to_mm():
    spec = spec_from_dict({"kind": "building", "units": "in",
                           "length": 480, "width": 360, "wall_height": 144})
    assert spec.length == pytest.approx(480 * MM_PER_IN)
    assert spec.width == pytest.approx(360 * MM_PER_IN)
    assert spec.wall_height == pytest.approx(144 * MM_PER_IN)


# --- automatic placement ----------------------------------------------------

def test_auto_places_beam_lines_and_post_grid():
    plan = frame_plan(_b())
    # A regular grid: every beam line carries the same number of posts.
    assert plan.n_lines >= 2
    assert plan.posts_per_beam == plan.n_bays + 1
    assert plan.n_posts == plan.n_lines * plan.posts_per_beam
    assert plan.n_beams == plan.n_lines


def test_clear_span_stays_within_safe_span():
    # The placer must insert enough posts that no clear span exceeds the safe span.
    plan = frame_plan(_b())
    assert plan.clear_span <= plan.max_span + 1.0
    # And it shouldn't over-build: dropping one bay would exceed the safe span.
    if plan.n_bays > 1:
        coarser = plan.beam_run / (plan.n_bays - 1)
        assert coarser > plan.max_span


def test_beam_spacing_controls_line_count():
    wide = frame_plan(_b(beam_spacing=9144))   # one bay across the width -> 2 lines
    tight = frame_plan(_b(beam_spacing=3000))  # more lines
    assert wide.n_lines == 2
    assert tight.n_lines > wide.n_lines


def test_stiffer_beam_needs_fewer_posts():
    shallow = frame_plan(_b(beam_depth=235))           # 2x10
    deep = frame_plan(_b(beam_depth=400))              # deeper girder
    assert deep.max_span > shallow.max_span
    assert deep.n_bays <= shallow.n_bays


def test_explicit_post_spacing_overrides_auto():
    plan = frame_plan(_b(length=12000, post_spacing=3000))
    assert plan.n_bays == 4   # 12000 / 3000
    assert plan.posts_per_beam == 5


def test_span_direction_orients_the_beams():
    along_len = frame_plan(_b())                       # default: beams run length
    across = frame_plan(_b(span_direction="width"))    # beams run across width
    assert along_len.beam_run == pytest.approx(12192)
    assert across.beam_run == pytest.approx(9144)


def test_posts_run_floor_to_underside_of_beam():
    spec = _b()
    plan = frame_plan(spec)
    assert plan.post_height == pytest.approx(spec.wall_height - spec.beam_depth)
    # Beams sit on top: a beam's top face reaches the wall height.
    beam = plan.beams[0]
    beam_top = beam.center[2] + beam.size[2] / 2
    assert beam_top == pytest.approx(spec.wall_height)


# --- geometry / cut list ----------------------------------------------------

def test_panels_cover_every_beam_and_post():
    spec = _b()
    plan = frame_plan(spec)
    panels = panel_layout(spec)
    cats = [p.category for p in panels]
    assert cats.count("beam") == plan.n_beams
    assert cats.count("post") == plan.n_posts


def test_cutlist_counts_match_the_plan():
    spec = _b()   # built-up default: 3 plies per girder
    plan = frame_plan(spec)
    cl = generate_cutlist(spec)
    plies = next(p for p in cl.parts if p.name == "Carrying beam ply")
    posts = next(p for p in cl.parts if p.name == "Support post")
    assert plies.qty == plan.n_lines * spec.beam_plies
    assert posts.qty == plan.n_posts
    assert all(p.id for p in cl.parts)   # every part got a stable ID
    # One base anchor and one cap per post.
    caps = next(h for h in cl.hardware if "cap" in h.name.lower())
    anchors = next(h for h in cl.hardware if "anchor" in h.name.lower())
    assert caps.qty == plan.n_posts and anchors.qty == plan.n_posts


def test_engineered_beam_is_a_single_member_not_plies():
    cl = generate_cutlist(_b(beam_material="glulam", beam_plies=1))
    names = [p.name for p in cl.parts]
    assert "Carrying beam" in names
    assert "Carrying beam ply" not in names


def test_estimate_and_joinery_and_assembly_run():
    spec = _b()
    assert estimate(spec).total > 0
    assert len(joinery_schedule(spec).ops) >= 2
    subs = [s.name for s in assembly_plan(spec).subassemblies]
    assert subs == ["Posts", "Beams", "Final"]


# --- validation -------------------------------------------------------------

def test_default_frame_validates_ok():
    assert validate(_b()).ok


def test_over_span_is_flagged_with_a_fix():
    # Force posts far enough apart that the beam can't carry the span.
    res = validate(_b(post_spacing=12000, length=12192))
    assert not res.ok
    err = next(i for i in res.issues if i.rule_id == "BLD-002")
    assert err.direction == "max" and err.observed > err.limit


def test_beam_taller_than_wall_is_an_error():
    res = validate(_b(beam_depth=4000, wall_height=3658))
    assert not res.ok
    assert any(i.rule_id == "BLD-001" for i in res.issues)


def test_slender_post_warns():
    res = validate(_b(post_size=60, wall_height=3658, beam_depth=200))
    assert any(i.rule_id == "BLD-003" for i in res.issues)


def test_beam_on_the_flat_warns():
    res = validate(_b(beam_width=286, beam_depth=114))
    assert any(i.rule_id == "BLD-004" for i in res.issues)


def test_negative_dimension_is_an_error():
    res = validate(_b(length=-1))
    assert not res.ok
    assert any(i.field == "length" and i.severity == "error" for i in res.issues)


# --- engineering ------------------------------------------------------------

def test_max_beam_span_inverts_deflection():
    # A span at the limit should deflect exactly span/ratio.
    b, h, E, w, R = 114.0, 286.0, 8300.0, 2.0, 240.0
    L = engineering.max_beam_span(b, h, E, w, deflection_ratio=R)
    delta = engineering.shelf_deflection(L, b, h, w, E)
    assert delta == pytest.approx(L / R, rel=1e-6)


def test_lvl_is_stiffer_than_built_up():
    assert engineering.beam_modulus("lvl") > engineering.beam_modulus("built_up")
