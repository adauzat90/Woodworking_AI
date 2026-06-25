"""Spec diffing + the /api/diff endpoint (design revision compare)."""

from fastapi.testclient import TestClient

from woodworking_ai.diffing import spec_diff, diff_summary
from woodworking_ai.web import app

client = TestClient(app)


def test_no_changes_for_identical_specs():
    a = {"width": 600, "material": {"carcass": 18}}
    assert spec_diff(a, dict(a)) == []
    assert diff_summary([]) == "no changes"


def test_scalar_change_reported():
    changes = spec_diff({"width": 600}, {"width": 700})
    assert changes == [{"path": "width", "from": 600, "to": 700}]


def test_nested_change_uses_dotted_path():
    changes = spec_diff({"material": {"carcass": 18}}, {"material": {"carcass": 19}})
    assert changes == [{"path": "material.carcass", "from": 18, "to": 19}]


def test_list_changes_compared_whole():
    changes = spec_diff({"drawers": [1]}, {"drawers": [1, 2]})
    assert len(changes) == 1 and changes[0]["path"] == "drawers"


def test_diff_endpoint_normalises_and_reports():
    base = {"cabinet_type": "base", "name": "X", "width": 600, "height": 720,
            "depth": 560, "doors": 2}
    changed = dict(base, width=900)
    r = client.post("/api/diff", json={"from": base, "to": changed})
    assert r.status_code == 200
    d = r.json()
    paths = [c["path"] for c in d["changes"]]
    assert "width" in paths
    assert "600" in d["summary"] or "change" in d["summary"]


def test_diff_endpoint_identical_specs_have_no_changes():
    spec = {"cabinet_type": "base", "name": "X", "width": 600, "height": 720,
            "depth": 560}
    r = client.post("/api/diff", json={"from": spec, "to": dict(spec)})
    assert r.json()["changes"] == []
