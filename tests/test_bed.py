"""Bed (G1) — a knock-down headboard + footboard + side rails + slat deck.

Proves the bed leaf type flows through the whole pipeline with no edit to any
generic stage, that it sizes from a standard mattress, joins with knock-down
hardware, and that its built envelope matches the spec (so the Critic passes).
"""

import pytest

from woodworking_ai import (
    BedSpec, BedSize, BedConnector,
    Project, Component, validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN, MATTRESS_SIZES
from woodworking_ai.dispatch import spec_kind, BED
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def _bed(**kw) -> BedSpec:
    base = dict(name="Walnut Bed", size="queen", species="walnut")
    base.update(kw)
    return BedSpec(**base)


def test_dispatch_kind_and_spec_from_dict():
    assert spec_kind(_bed()) == BED
    assert isinstance(spec_from_dict({"kind": "bed", "size": "full"}), BedSpec)


def test_roundtrip_preserves_enums():
    spec = _bed(size="king", connector="hook_plate", panel=False)
    again = BedSpec.from_dict(spec.to_dict())
    assert again == spec
    assert again.size == BedSize.KING
    assert again.connector == BedConnector.HOOK_PLATE


def test_standard_size_sets_mattress():
    spec = _bed(size="queen")
    assert (spec.mattress_width, spec.mattress_length) == MATTRESS_SIZES[BedSize.QUEEN]
    # Overall width adds clearance + a rail each side; length adds the posts.
    assert spec.width > spec.mattress_width
    assert spec.depth > spec.mattress_length


def test_custom_size_uses_explicit_mattress():
    spec = _bed(size="custom", mattress_w=1400, mattress_l=2000)
    assert spec.mattress_width == 1400 and spec.mattress_length == 2000


def test_imperial_on_load_converts_to_mm():
    spec = BedSpec.from_dict(
        {"units": "in", "size": "custom", "mattress_w": 60, "mattress_l": 80,
         "post": 3, "head_height": 44})
    assert spec.units == "mm"
    assert spec.post == pytest.approx(3 * MM_PER_IN)
    assert spec.head_height == pytest.approx(44 * MM_PER_IN)


def test_slat_count_auto_and_explicit():
    assert _bed(slats=0).slat_count >= 3            # auto from the length
    assert _bed(slats=14).slat_count == 14


def test_panels_have_posts_rails_slats():
    panels = panel_layout(_bed())
    starts = {p.label.split()[0] for p in panels}
    assert {"Post", "Rail", "Side", "Slat"} <= starts
    # Auto slat count is reflected in the panel set.
    assert sum(p.label.startswith("Slat") for p in panels) == _bed().slat_count


def test_open_bed_has_no_infill_panel():
    panels = panel_layout(_bed(panel=False))
    assert not any("panel" in p.label.lower() for p in panels)


def test_cutlist_parts_and_knockdown_hardware():
    cl = generate_cutlist(_bed())
    names = [p.name for p in cl.parts]
    for expected in ("Post (head)", "Post (foot)", "Side rail", "Slat",
                     "Slat ledger"):
        assert expected in names
    assert all(p.id for p in cl.parts)
    hw = " ".join(h.name.lower() for h in cl.hardware)
    assert "bolt" in hw                              # default bed-bolt connector


def test_hook_plate_connector():
    cl = generate_cutlist(_bed(connector="hook_plate"))
    assert any("hook" in h.name.lower() for h in cl.hardware)
    assert not any("bolt" in h.name.lower() for h in cl.hardware)


def test_validate_sane_bed_passes():
    assert validate(_bed(size="full")).ok          # full is narrow enough, no sag warn


def test_validate_custom_requires_mattress_dims():
    assert not validate(_bed(size="custom", mattress_w=0, mattress_l=0)).ok


def test_validate_warns_wide_deck_needs_center_support():
    res = validate(_bed(size="king"))
    assert any(i.field == "slats" for i in res.warnings)


def test_validate_warns_footboard_taller_than_head():
    res = validate(_bed(head_height=500, foot_height=900))
    assert any(i.field == "foot_height" for i in res.warnings)


def test_joinery_is_knockdown_not_glued_rails():
    ops = joinery_schedule(_bed()).ops
    text = " ".join(o.operation for o in ops).lower()
    assert "mortise & tenon" in text          # headboard frame IS glued
    assert "bed-bolt" in text or "hook" in text   # rails are knock-down


def test_assembly_plan_phases():
    plan = assembly_plan(_bed())
    names = [s.name for s in plan.subassemblies]
    assert "Headboard" in names and "Footboard" in names
    assert "Side rails" in names


def test_estimate_prices_the_bed():
    assert estimate(_bed()).total > 0


def test_built_envelope_matches_spec():
    # The built model's bounding box must equal the spec's W/D/H so the Critic's
    # envelope check passes (the single-source-of-truth contract for a new leaf).
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    spec = _bed()
    dims = measure(build_model(spec))
    assert dims["width"] == pytest.approx(spec.width, abs=1.0)
    assert dims["depth"] == pytest.approx(spec.depth, abs=1.0)
    assert dims["height"] == pytest.approx(spec.height, abs=1.0)


def test_bed_inside_a_project():
    proj = Project(name="Guest room", components=[
        Component(spec=_bed(name="Bed", size="full"), x=0, label="bed"),
    ])
    assert validate(proj).ok
    assert estimate(proj).total > 0
