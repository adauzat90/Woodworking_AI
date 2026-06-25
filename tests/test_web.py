"""Tests for the FastAPI web app (uses TestClient; no live server)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from woodworking_ai.web import app  # noqa: E402

client = TestClient(app)

VALID_SPEC = {
    "cabinet_type": "base", "name": "Web Test", "width": 900, "height": 720,
    "depth": 560, "doors": 2, "shelves": 1, "drawers": [{"front_height": 140}],
    "toe_kick": {"height": 100, "setback": 50}, "reveal": 3,
}


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Woodworking AI" in r.text


def test_profile_endpoint_returns_defaults():
    r = client.get("/api/profile")
    assert r.status_code == 200
    d = r.json()
    assert d["construction"] == "frameless"
    assert "prices" in d and "sheet" in d


def test_build_applies_profile_construction_default():
    # A bare cabinet that omits construction; the profile should fill it.
    bare = {"cabinet_type": "base", "name": "Bare", "width": 600,
            "height": 720, "depth": 560, "doors": 2, "shelves": 1}
    r = client.post("/api/build", json={
        "spec": bare, "profile": {"construction": "face_frame"}})
    assert r.status_code == 200
    assert r.json()["spec"]["construction"] == "face_frame"


def test_build_constrains_to_profile_tooling():
    # A Domino joint with a hand-tools-only inventory: the bundle should flag it
    # with a substitute and mark the tool missing in the checklist.
    spec = {"cabinet_type": "base", "name": "Tooled", "width": 600,
            "height": 720, "depth": 560, "doors": 2, "shelves": 1,
            "joinery": "domino"}
    hand = {k: False for k in (
        "table_saw", "dado_set", "router", "router_table", "band_saw",
        "drill_press", "jointer", "planer", "doweling_jig", "pocket_jig",
        "domino", "biscuit_joiner", "dovetail_jig", "box_joint_jig",
        "mortiser", "shelf_pin_jig", "forstner_35")}
    hand.update(hand_tools=True, drill=True)
    r = client.post("/api/build", json={"spec": spec, "profile": {"tooling": hand}})
    assert r.status_code == 200
    d = r.json()
    assert any(w["field"] == "tooling" for w in d["warnings"])
    domino = [t for t in d["tools"] if "domino" in t["operation"].lower()]
    assert domino and domino[0]["owned"] is False


def test_build_without_tooling_lists_tools_unmarked():
    d = client.post("/api/build", json={"spec": VALID_SPEC}).json()
    assert d["tools"] and all(t["owned"] is None for t in d["tools"])
    assert not any(w["field"] == "tooling" for w in d["warnings"])


def test_health_reports_capabilities():
    r = client.get("/api/health")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    assert {"render", "glb", "llm", "convex"} <= caps.keys()


def test_convex_url_injected_when_configured(monkeypatch):
    monkeypatch.setenv("CONVEX_URL", "https://demo.convex.cloud")
    assert "demo.convex.cloud" in client.get("/").text


def test_convex_url_absent_by_default(monkeypatch):
    monkeypatch.delenv("CONVEX_URL", raising=False)
    body = client.get("/").text
    assert "window.__CONVEX_URL__=''" in body


def test_build_returns_full_bundle():
    r = client.post("/api/build", json={"spec": VALID_SPEC})
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert d["critique"]["report"]["interference_count"] == 0
    assert len(d["cutlist"]) > 0
    assert d["estimate"]["total"] > 0
    assert d["drilling"]["total_holes"] > 0


def test_build_render_png_present():
    pytest.importorskip("matplotlib")
    d = client.post("/api/build", json={"spec": VALID_SPEC}).json()
    assert (d["render_png"] or "").startswith("data:image/png;base64,")


def test_build_glb_present_with_build123d():
    pytest.importorskip("build123d")
    d = client.post("/api/build", json={"spec": VALID_SPEC}).json()
    assert (d["glb"] or "").startswith("data:model/gltf-binary;base64,")


def test_pricing_defaults_endpoint():
    r = client.get("/api/pricing")
    assert r.status_code == 200
    body = r.json()
    assert "shop_rate_per_hour" in body["prices"]
    assert "frame" in body["prices"]["board_foot_price"]
    assert body["sheet"]["length"] > 0


def test_build_accepts_price_overrides():
    """A higher shop rate raises labour cost; the bundle echoes the new rate."""
    base = client.post("/api/build", json={"spec": VALID_SPEC, "glb": False}).json()
    dear = client.post("/api/build", json={
        "spec": VALID_SPEC, "glb": False,
        "prices": {"shop_rate_per_hour": 500.0}}).json()
    assert dear["estimate"]["labour"] > base["estimate"]["labour"]
    assert dear["estimate"]["total"] > base["estimate"]["total"]


def test_build_board_foot_override_changes_lumber_cost():
    table = {"kind": "table", "name": "T", "width": 1500, "depth": 850,
             "height": 740}
    base = client.post("/api/build", json={"spec": table, "glb": False}).json()
    dear = client.post("/api/build", json={
        "spec": table, "glb": False,
        "prices": {"board_foot_price": {"top": 999.0}}}).json()
    assert dear["estimate"]["lumber"] > base["estimate"]["lumber"]


def test_build_sheet_size_override_changes_sheet_count():
    """A tiny sheet forces more sheets than the standard 8x4."""
    base = client.post("/api/build", json={"spec": VALID_SPEC, "glb": False}).json()
    small = client.post("/api/build", json={
        "spec": VALID_SPEC, "glb": False,
        "sheet": {"length": 1000, "width": 600}}).json()
    assert small["estimate"]["total_sheets"] >= base["estimate"]["total_sheets"]


def test_build_garbage_prices_falls_back_to_defaults():
    """Non-numeric overrides are ignored rather than 500-ing the build."""
    r = client.post("/api/build", json={
        "spec": VALID_SPEC, "glb": False,
        "prices": {"shop_rate_per_hour": "free", "board_foot_price": {"top": None}}})
    assert r.status_code == 200
    assert r.json()["estimate"]["total"] > 0


def test_build_invalid_spec_reports_errors():
    d = client.post("/api/build", json={"spec": {"cabinet_type": "base",
                                                 "width": -5}}).json()
    assert d["valid"] is False
    assert any(e["field"] == "width" for e in d["errors"])


def test_build_diagonal_corner():
    spec = {"cabinet_type": "corner_diagonal", "name": "D", "width": 900,
            "height": 720, "depth": 900, "doors": 1, "shelves": 2,
            "corner_cut": 450, "toe_kick": {"height": 100, "setback": 50}}
    d = client.post("/api/build", json={"spec": spec}).json()
    assert d["valid"] is True
    assert any("angled" in p["notes"] for p in d["cutlist"])


def test_design_without_key_returns_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/design", json={"prompt": "a base cabinet"})
    assert r.status_code == 503


def test_design_empty_prompt_400():
    assert client.post("/api/design", json={"prompt": "  "}).status_code == 400


# --- exports -------------------------------------------------------------

def test_export_cutlist_csv():
    r = client.post("/api/export/cutlist", json={"spec": VALID_SPEC})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("id,part,qty")
    assert "attachment" in r.headers["content-disposition"]


def test_export_drilling_csv():
    r = client.post("/api/export/drilling", json={"spec": VALID_SPEC})
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("id,part,operation")


def test_export_dxf():
    r = client.post("/api/export/dxf", json={"spec": VALID_SPEC})
    assert r.status_code == 200
    assert r.text.startswith("0\nSECTION")


def test_export_step_and_glb_with_build123d():
    pytest.importorskip("build123d")
    for fmt in ("step", "stl", "glb"):
        r = client.post(f"/api/export/{fmt}", json={"spec": VALID_SPEC})
        assert r.status_code == 200
        assert len(r.content) > 0


def test_export_unknown_format_415():
    r = client.post("/api/export/foo", json={"spec": VALID_SPEC})
    assert r.status_code == 415


# --- revision diff + price delta (D2) ------------------------------------

def test_diff_reports_field_changes_with_path_from_to():
    """Saving a changed spec yields {path, from, to} rows for each edit."""
    older = dict(VALID_SPEC)
    newer = dict(VALID_SPEC, width=1200, shelves=3)
    d = client.post("/api/diff", json={"from": older, "to": newer}).json()
    by_path = {c["path"]: c for c in d["changes"]}
    assert by_path["width"]["from"] == 900 and by_path["width"]["to"] == 1200
    assert by_path["shelves"]["from"] == 1 and by_path["shelves"]["to"] == 3
    assert "change(s)" in d["summary"]


def test_diff_identical_specs_no_changes_zero_delta():
    d = client.post("/api/diff", json={"from": VALID_SPEC, "to": VALID_SPEC}).json()
    assert d["changes"] == []
    assert d["summary"] == "no changes"
    assert d["quote"]["price_delta"] == 0.0


def test_diff_price_delta_positive_when_bigger():
    """A wider cabinet with more shelves costs more — delta is positive."""
    older = dict(VALID_SPEC)
    newer = dict(VALID_SPEC, width=1200, shelves=4)
    q = client.post("/api/diff", json={"from": older, "to": newer}).json()["quote"]
    assert q["price_to"] > q["price_from"]
    assert q["price_delta"] > 0
    assert round(q["price_to"] - q["price_from"], 2) == q["price_delta"]
    # The extra shelves show up as added parts.
    assert q["parts_added"] or q["parts_changed"]


def test_diff_price_delta_negative_when_smaller():
    older = dict(VALID_SPEC, width=1200, shelves=4)
    newer = dict(VALID_SPEC, width=600, shelves=0, doors=1)
    q = client.post("/api/diff", json={"from": older, "to": newer}).json()["quote"]
    assert q["price_delta"] < 0
    assert q["price_to"] < q["price_from"]
    assert q["parts_removed"] or q["parts_changed"]


def test_diff_bad_spec_returns_400():
    r = client.post("/api/diff", json={"from": {"cabinet_type": "nope"},
                                       "to": VALID_SPEC})
    assert r.status_code == 400


# --- multi-component projects -------------------------------------------------

PROJECT_SPEC = {
    "kind": "project", "name": "Galley",
    "components": [
        {"label": "A", "x": 0, "y": 0,
         "spec": {"cabinet_type": "base", "width": 900, "doors": 2, "shelves": 1}},
        {"label": "B", "x": 900, "y": 0,
         "spec": {"cabinet_type": "base", "width": 600,
                  "drawers": [{"front_height": 160}]}},
    ],
}


def test_build_project_returns_aggregated_bundle():
    d = client.post("/api/build", json={"spec": PROJECT_SPEC, "glb": False}).json()
    assert d["valid"] is True
    assert d["spec"]["kind"] == "project"
    assert d["critique"]["report"]["component_count"] == 2
    # Combined cut list is tagged per component, holes aggregate across the run.
    assert any(p["name"].startswith("A · ") for p in d["cutlist"])
    assert d["drilling"]["total_holes"] > 0


def test_build_project_detects_placement_collision():
    bad = {"kind": "project", "components": [
        {"label": "A", "x": 0, "y": 0, "spec": {"cabinet_type": "base", "width": 900}},
        {"label": "B", "x": 300, "y": 0, "spec": {"cabinet_type": "base", "width": 900}},
    ]}
    d = client.post("/api/build", json={"spec": bad, "glb": False}).json()
    assert d["valid"] is False
    assert any(e["field"] == "placement" for e in d["errors"])


def test_export_project_cutlist_imperial():
    r = client.post("/api/export/cutlist",
                    json={"spec": PROJECT_SPEC, "units": "imperial"})
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("id,part,qty,length_in")


# --- sub-assemblies through the API (the SPA's "Project / assembly" samples) ---

# Define a sub-assembly once, place independent copies by ref (SAMPLE_REUSE).
REUSE_SPEC = {
    "kind": "project", "name": "Wall of cabinets",
    "definitions": {
        "wall_pair": {
            "kind": "assembly", "name": "Wall pair",
            "components": [
                {"x": 0, "spec": {"cabinet_type": "wall", "width": 600,
                                  "toe_kick": None}},
                {"x": 600, "spec": {"cabinet_type": "wall", "width": 600,
                                    "toe_kick": None}},
            ],
        },
    },
    "components": [
        {"ref": "wall_pair", "x": 0, "y": 0, "label": "Upper-L"},
        {"ref": "wall_pair", "x": 0, "y": 1500, "label": "Upper-R"},
    ],
}

# A sub-assembly nested inline as one component (SAMPLE_NESTED).
NESTED_SPEC = {
    "kind": "project", "name": "Galley kitchen",
    "components": [
        {"label": "Bank", "x": 0, "y": 0, "spec": {
            "kind": "assembly", "name": "Drawer bank", "components": [
                {"x": 0, "spec": {"cabinet_type": "base", "width": 600,
                                  "drawers": [{"front_height": 160}]}},
                {"x": 600, "spec": {"cabinet_type": "base", "width": 600,
                                    "drawers": [{"front_height": 160}]}},
            ]}},
        {"label": "Sink", "x": 1200, "y": 0, "spec": {
            "cabinet_type": "base", "width": 900, "doors": 2, "shelves": 1}},
    ],
}


def test_build_reuse_resolves_refs_and_aggregates():
    d = client.post("/api/build", json={"spec": REUSE_SPEC, "glb": False}).json()
    assert d["valid"] is True
    # The two ref placements stay terse in the echoed spec (no inline spec).
    assert all(c.get("ref") == "wall_pair" for c in d["spec"]["components"])
    # Both copies' parts are in the one combined cut list.
    assert any(p["name"].startswith("Upper-L · ") for p in d["cutlist"])
    assert any(p["name"].startswith("Upper-R · ") for p in d["cutlist"])


def test_build_nested_assembly_aggregates_and_validates():
    d = client.post("/api/build", json={"spec": NESTED_SPEC, "glb": False}).json()
    assert d["valid"] is True
    # The bank's two cabinets are tagged under the nested component.
    assert any(p["name"].startswith("Bank · ") for p in d["cutlist"])
    assert d["drilling"]["total_holes"] > 0


def test_build_rejects_cyclic_subassembly():
    bad = {"kind": "project",
           "definitions": {"a": {"kind": "assembly", "components": [{"ref": "b"}]},
                           "b": {"kind": "assembly", "components": [{"ref": "a"}]}},
           "components": [{"ref": "a"}]}
    r = client.post("/api/build", json={"spec": bad, "glb": False})
    assert r.status_code == 400          # bad spec, surfaced not 500'd


def test_build_bundle_lists_model_sections():
    d = client.post("/api/build", json={"spec": VALID_SPEC}).json()
    assert "model_sections" in d
    assert "Carcass" in d["model_sections"]


def test_model_endpoint_degrades_without_build123d():
    # Returns a GLB (200) when build123d is present, else a clean 503 — never 500.
    r = client.post("/api/model", json={"spec": VALID_SPEC, "factor": 1.0})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("model/gltf-binary")


def test_model_endpoint_rejects_invalid_spec():
    bad = dict(VALID_SPEC, width=-5)
    r = client.post("/api/model", json={"spec": bad})
    assert r.status_code == 422
