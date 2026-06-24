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
    assert r.text.splitlines()[0].startswith("part,qty")
    assert "attachment" in r.headers["content-disposition"]


def test_export_drilling_csv():
    r = client.post("/api/export/drilling", json={"spec": VALID_SPEC})
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("part,operation")


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
