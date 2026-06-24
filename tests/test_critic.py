"""Tests for the Critic agent and the shared panel layout (no CAD / API key)."""

import pytest

from woodworking_ai import CabinetSpec, Material, ToeKick, Drawer
from woodworking_ai.dsl import BackStyle
from woodworking_ai.geometry import PanelBox, panel_layout
from woodworking_ai.agents.critic import critique, _overlap, _interferences


def base_spec(**overrides) -> CabinetSpec:
    defaults = dict(
        name="Test", width=600, height=720, depth=560,
        material=Material(carcass=18, back=6, door=18, shelf=18),
        toe_kick=ToeKick(height=100, setback=50),
        shelves=1, doors=2, drawers=[], reveal=3,
    )
    defaults.update(overrides)
    return CabinetSpec(**defaults)


# --- layout --------------------------------------------------------------

def test_layout_has_carcass_and_fronts():
    panels = panel_layout(base_spec())
    cats = {p.category for p in panels}
    assert {"carcass", "back", "shelf", "toe", "front"} <= cats


def test_layout_matches_builder_when_cad_present():
    # The builder must consume the same layout; if build123d is installed the
    # part counts must agree, otherwise this is skipped.
    b3d = pytest.importorskip("build123d")  # noqa: F841
    from woodworking_ai.builder import build_model
    spec = base_spec()
    model = build_model(spec)
    assert len(model.children) == len(panel_layout(spec))


# --- envelope ------------------------------------------------------------

def test_correct_cabinet_passes_critique():
    crit = critique(base_spec())
    assert crit.ok
    assert crit.report["interference_count"] == 0


def test_envelope_matches_spec_dimensions():
    spec = base_spec(width=800, height=900, depth=600)
    r = critique(spec).report
    assert r["width"] == pytest.approx(800)
    assert r["height"] == pytest.approx(900)
    assert r["depth"] == pytest.approx(600)


def test_fronts_sit_proud_in_depth():
    spec = base_spec()
    r = critique(spec).report
    # Fronts add the door thickness in front of the carcass.
    assert r["depth_with_fronts"] == pytest.approx(spec.depth + spec.material.door)


def test_report_has_expected_keys():
    r = critique(base_spec()).report
    for key in ("width", "height", "depth", "opening_width", "opening_height",
                "panel_count", "front_coverage_pct", "sheet_area_m2",
                "interference_count"):
        assert key in r


# --- interference detection (the core geometric check) -------------------

def test_overlap_detects_interpenetration():
    a = PanelBox("A", (100, 100, 100), (0, 0, 0))
    b = PanelBox("B", (100, 100, 100), (50, 0, 0))  # overlaps by 50 in x
    ox, oy, oz = _overlap(a, b)
    assert ox == pytest.approx(50)
    assert oy > 0 and oz > 0


def test_touching_faces_are_not_interference():
    a = PanelBox("A", (100, 100, 100), (0, 0, 0))
    b = PanelBox("B", (100, 100, 100), (100, 0, 0))  # faces touch at x=50
    assert _interferences([a, b]) == []


def test_overlapping_panels_are_flagged():
    a = PanelBox("A", (100, 100, 100), (0, 0, 0))
    b = PanelBox("B", (100, 100, 100), (40, 40, 40))
    hits = _interferences([a, b])
    assert len(hits) == 1
    assert hits[0][2] > 0  # positive overlap volume


def test_real_cabinets_have_no_interferences():
    for spec in (
        base_spec(),
        base_spec(doors=1, width=450),
        base_spec(doors=0, drawers=[Drawer(140), Drawer(180), Drawer(220)]),
        base_spec(back=BackStyle.APPLIED),
        base_spec(shelves=3),
    ):
        assert critique(spec).report["interference_count"] == 0, spec.name


# --- coverage ------------------------------------------------------------

def test_doored_cabinet_has_high_coverage():
    assert critique(base_spec()).report["front_coverage_pct"] > 80


def test_open_cabinet_warns():
    crit = critique(base_spec(doors=0, drawers=[]))
    assert any(w.kind == "coverage" for w in crit.warnings)


def test_large_reveal_low_coverage_warns():
    crit = critique(base_spec(reveal=100))
    assert any(w.kind == "coverage" for w in crit.warnings)


# --- feedback / report text ----------------------------------------------

def test_feedback_is_clean_when_ok():
    assert "verified" in critique(base_spec()).as_feedback().lower()


def test_report_text_renders():
    text = critique(base_spec()).report_text()
    assert "Critic report" in text
    assert "interferences" in text


# --- B-Rep interference (build123d-gated, graceful without it) -----------

def test_brep_check_runs_or_skips_gracefully():
    crit = critique(base_spec(), brep=True)
    try:
        import build123d  # noqa: F401
        # With build123d present, a correct cabinet has no real intersections.
        assert crit.report.get("brep_interference_count", 0) == 0
        assert crit.ok
    except ImportError:
        # Without it, the check is skipped with a warning, never an error.
        assert crit.ok
        assert any(i.kind == "geometry" for i in crit.warnings)


def test_brep_interferences_detects_overlap_when_cad_present():
    b3d = pytest.importorskip("build123d")
    from woodworking_ai.agents.critic import _brep_interferences
    a = b3d.Pos(0, 0, 0) * b3d.Box(100, 100, 100)
    a.label = "A"
    b = b3d.Pos(40, 0, 0) * b3d.Box(100, 100, 100)
    b.label = "B"
    model = b3d.Compound(children=[a, b])
    hits = _brep_interferences(model)
    assert len(hits) == 1 and hits[0][2] > 0
