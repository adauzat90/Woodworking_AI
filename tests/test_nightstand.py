"""Nightstand (G1) — a small legged cabinet with a drawer and a lower shelf."""

import pytest

from woodworking_ai import (
    NightstandSpec, Project, Component,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, NIGHTSTAND
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan


def _ns(**kw) -> NightstandSpec:
    base = dict(name="Nightstand", width=450, depth=400, height=600,
                species="walnut")
    base.update(kw)
    return NightstandSpec(**base)


def test_dispatch_and_spec_from_dict():
    assert spec_kind(_ns()) == NIGHTSTAND
    assert isinstance(spec_from_dict({"kind": "nightstand", "width": 400}),
                      NightstandSpec)


def test_roundtrip_and_imperial():
    again = NightstandSpec.from_dict(_ns(drawers=2, pull="bar").to_dict())
    assert again == _ns(drawers=2, pull="bar")
    imp = NightstandSpec.from_dict({"units": "in", "width": 18, "height": 24})
    assert imp.units == "mm" and imp.width == pytest.approx(18 * MM_PER_IN)


def test_panels_have_top_legs_apron_drawer_shelf():
    starts = {p.label.split()[0] for p in panel_layout(_ns())}
    assert {"Top", "Leg", "Apron", "Front", "Drawer", "Shelf"} <= starts


def test_no_drawer_no_shelf_variants():
    assert not any("Drawer" in p.label for p in panel_layout(_ns(drawers=0)))
    assert not any(p.label == "Shelf" for p in panel_layout(_ns(shelf=False)))


def test_cutlist_drawer_box_and_hardware():
    cl = generate_cutlist(_ns(drawers=1))
    names = [p.name for p in cl.parts]
    for n in ("Top", "Leg", "Drawer front", "Drawer side", "Drawer bottom",
              "Shelf"):
        assert n in names
    hw = " ".join(h.name.lower() for h in cl.hardware)
    assert "slide" in hw and "pull" in hw


def test_pull_none_drops_pull():
    cl = generate_cutlist(_ns(pull="none"))
    assert not any("pull" in h.name.lower() for h in cl.hardware)


def test_validate_passes_and_racking_warning():
    assert validate(_ns()).ok
    assert any(i.field == "joinery" for i in validate(_ns(joinery="pocket")).warnings)


def test_validate_rejects_bad_dims():
    assert not validate(_ns(width=0)).ok
    assert not validate(_ns(leg_inset=300)).ok      # legs don't fit


def test_joinery_and_assembly():
    ops = " ".join(o.operation for o in joinery_schedule(_ns()).ops).lower()
    assert "leg-to-apron" in ops
    names = [s.name for s in assembly_plan(_ns()).subassemblies]
    assert "Base" in names and "Drawer" in names


def test_estimate_and_project():
    assert estimate(_ns()).total > 0
    proj = Project(name="Pair", components=[
        Component(spec=_ns(name="A"), x=0, label="A"),
        Component(spec=_ns(name="B"), x=600, label="B")])
    assert validate(proj).ok and estimate(proj).total > 0


def test_built_envelope_matches_spec():
    pytest.importorskip("build123d")
    from woodworking_ai.builder import build_model, measure
    s = _ns()
    d = measure(build_model(s))
    assert d["width"] == pytest.approx(s.width, abs=1.0)
    assert d["height"] == pytest.approx(s.height, abs=1.0)


def test_graduated_drawer_fronts():
    # Per-drawer heights produce a numbered part set per height; the panels are
    # stacked with the right individual heights.
    spec = _ns(drawers=2, drawer_front_heights=[120, 200])
    assert spec.front_heights(2) == [120.0, 200.0]
    fronts = [p for p in panel_layout(spec) if p.label.startswith("Drawer front")]
    heights = sorted(round(p.size[2]) for p in fronts)
    assert heights == [120, 200]
    # A uniform stack stays one aggregated cut-list row.
    uni = generate_cutlist(_ns(drawers=2)).parts
    assert sum(p.name == "Drawer front" for p in uni) == 1


def test_drawer_corner_joint_field_drives_joinery_and_tooling():
    from woodworking_ai.tooling import (required_operations, tooling_advisories,
                                        ShopTooling)
    spec = _ns(drawers=1, drawer_corner_joint="dovetail", joinery="pocket")
    ops = joinery_schedule(spec).ops
    assert any("dovetail" in o.operation for o in ops)
    # required_operations now lists the drawer corner so a shop check can fire.
    joints = {r.joint for r in required_operations(spec)}
    assert "dovetail" in joints
    no_dt = ShopTooling.from_names(["table_saw", "router", "drill", "pocket_jig"])
    adv = [m for _, _, m in tooling_advisories(spec, no_dt) if "box corners" in m]
    assert adv and "switch to" in adv[0]
    # The default rabbet corner is makeable in that shop — no drawer advisory.
    ok = _ns(drawers=1, joinery="pocket")          # default corner = rabbet
    assert not [m for _, _, m in tooling_advisories(ok, no_dt)
                if "box corners" in m]


def test_pocket_joinery_shows_holes_in_drilling_schedule():
    from woodworking_ai.drilling import drilling_schedule
    pocket = drilling_schedule(_ns(drawers=1, joinery="pocket"))
    assert any("pocket" in o.operation.lower() for o in pocket.ops)
    assert pocket.total_holes > 0
    # A mortise-and-tenon nightstand has no pocket holes.
    mt = drilling_schedule(_ns(drawers=1, joinery="mortise_tenon"))
    assert not any("pocket" in o.operation.lower() for o in mt.ops)


def test_three_graduated_drawers():
    # A nightstand supports up to three drawers; all three must appear with
    # their individual graduated heights (the count cap used to drop the third).
    spec = _ns(drawers=3, drawer_front_heights=[120, 155, 195])
    fronts = [p for p in generate_cutlist(spec).parts
              if p.name.startswith("Drawer front")]
    assert sorted(round(p.width) for p in fronts) == [120, 155, 195]
    assert sum(l.label.startswith("Drawer front") for l in panel_layout(spec)) == 3
    assert validate(spec).ok


def test_mortise_and_tenon_aliases_resolve_not_pocket():
    # A natural M&T spelling must resolve to the enum, not silently degrade to a
    # string (which made the leg joint fall back to pocket-hole).
    from woodworking_ai.dsl import Joinery
    for alias in ("mortise_and_tenon", "mortise-and-tenon", "M&T"):
        spec = _ns(joinery=alias)
        assert spec.joinery == Joinery.MORTISE_TENON, alias
        leg = next(o for o in joinery_schedule(spec).ops if "leg" in o.part.lower())
        assert "pocket" not in leg.tool.lower(), alias
    # The strict cabinet load path resolves the alias too, but still rejects a
    # genuinely unknown joint.
    assert spec_from_dict({"kind": "cabinet", "cabinet_type": "base",
                           "joinery": "M&T"}).joinery == Joinery.MORTISE_TENON
    import pytest as _pytest
    with _pytest.raises(ValueError):
        spec_from_dict({"kind": "cabinet", "cabinet_type": "base",
                        "joinery": "frobnicate"})
