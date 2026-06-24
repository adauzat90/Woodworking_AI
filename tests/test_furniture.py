"""Tests for non-cabinet furniture — the table type and the spec factory."""

import json

import pytest

from woodworking_ai import (
    TableSpec, spec_from_dict, CabinetSpec, validate, generate_cutlist, estimate,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique
from woodworking_ai.service import build_result


def table(**o) -> TableSpec:
    d = dict(name="T", width=1400, depth=800, height=740, leg=60,
             apron_height=90, top_thickness=25, leg_inset=40)
    d.update(o)
    return TableSpec(**d)


# --- factory -------------------------------------------------------------

def test_factory_picks_table_by_kind():
    assert isinstance(spec_from_dict({"kind": "table", "width": 1200}), TableSpec)


def test_factory_picks_table_by_leg_field():
    assert isinstance(spec_from_dict({"width": 1200, "leg": 60}), TableSpec)


def test_factory_defaults_to_cabinet():
    assert isinstance(spec_from_dict({"cabinet_type": "base", "width": 600}),
                      CabinetSpec)


def test_table_roundtrips():
    t = table()
    assert TableSpec.from_json(t.to_json()).to_dict() == t.to_dict()


# --- geometry ------------------------------------------------------------

def test_table_has_top_four_legs_four_aprons():
    labels = [p.label for p in panel_layout(table())]
    assert labels.count("Top") == 1
    assert sum(1 for l in labels if l.startswith("Leg")) == 4
    assert sum(1 for l in labels if l.startswith("Apron")) == 4


def test_table_envelope_matches_spec():
    r = critique(table(width=1500, depth=900, height=750)).report
    assert r["width"] == pytest.approx(1500)
    assert r["depth"] == pytest.approx(900)
    assert r["height"] == pytest.approx(750)


def test_table_no_interference():
    assert critique(table()).report["interference_count"] == 0


def test_table_real_brep_clean():
    pytest.importorskip("build123d")
    crit = critique(table(), use_cad=True, brep=True)
    assert crit.ok
    assert crit.report["brep_interference_count"] == 0


# --- cut list / estimate / pipeline -------------------------------------

def test_table_cutlist_parts():
    names = {p.name for p in generate_cutlist(table()).parts}
    assert {"Top", "Leg", "Apron (long)", "Apron (short)"} == names


def test_table_estimate_positive():
    assert estimate(table()).total > 0


def test_table_build_result_is_finite_json():
    res = build_result(table(), want_png=False, want_glb=False)
    assert res["valid"] is True
    json.dumps(res, allow_nan=False)
    assert res["drilling"]["total_holes"] == 0  # no holes on a table


# --- validation ----------------------------------------------------------

def test_table_too_short_for_apron_invalid():
    assert not validate(table(height=100)).ok


def test_table_legs_dont_fit_invalid():
    assert not validate(table(leg_inset=800)).ok


def test_table_nan_rejected():
    assert not validate(table(width=float("nan"))).ok


# --- web -----------------------------------------------------------------

def test_table_via_web_api():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from woodworking_ai.web import app
    c = TestClient(app)
    r = c.post("/api/build", json={"spec": {"kind": "table", "width": 1500,
                                            "depth": 850, "height": 740}})
    assert r.status_code == 200
    d = r.json()
    assert d["valid"] is True
    assert any(p["name"] == "Top" for p in d["cutlist"])
