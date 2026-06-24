"""Edge-case and robustness tests across the whole pipeline."""

import json
import math

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Construction, Material, ToeKick, Drawer,
    validate, generate_cutlist, estimate, drilling_schedule,
)
from woodworking_ai.service import build_result
from woodworking_ai.validator import MAX_DIMENSION, MAX_SHELVES


def base(**o) -> CabinetSpec:
    d = dict(name="Edge", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- every type/construction goes through the pipeline cleanly -----------

CASES = [
    base(),
    base(cabinet_type=CabinetType.WALL, depth=330, toe_kick=None),
    base(cabinet_type=CabinetType.TALL, height=2100, shelves=5),
    base(construction=Construction.FACE_FRAME),
    base(construction=Construction.FACE_FRAME, center_mullion=True),
    base(cabinet_type=CabinetType.CORNER_BLIND, width=900, blind_width=350, doors=1),
    base(cabinet_type=CabinetType.CORNER_DIAGONAL, width=900, depth=900,
         corner_cut=450, doors=1, shelves=2),
    base(doors=0, drawers=[Drawer(140), Drawer(180), Drawer(220)]),
    base(doors=0, shelves=0, drawers=[]),  # empty open box
]


@pytest.mark.parametrize("spec", CASES, ids=lambda s: s.name + ":" + s.cabinet_type.value)
def test_pipeline_runs_for_every_case(spec):
    assert validate(spec).ok
    assert generate_cutlist(spec).parts
    assert estimate(spec).total > 0
    drilling_schedule(spec)  # must not raise


@pytest.mark.parametrize("spec", CASES, ids=lambda s: s.name + ":" + s.cabinet_type.value)
def test_build_result_is_finite_json(spec):
    res = build_result(spec, want_png=False, want_glb=False)
    assert res["valid"] is True
    # No NaN/inf anywhere — strict JSON must serialise.
    json.dumps(res, allow_nan=False)


# --- pathological inputs are rejected, not crashed -----------------------

@pytest.mark.parametrize("bad", [
    {"width": float("nan")},
    {"height": float("inf")},
    {"depth": -10},
    {"width": 0},
    {"width": MAX_DIMENSION + 1},
    {"shelves": MAX_SHELVES + 1},
    {"shelves": 10**9},
    {"reveal": float("nan")},
    {"material": Material(carcass=0)},
])
def test_pathological_specs_are_invalid(bad):
    assert not validate(base(**bad)).ok


def test_huge_height_does_not_hang_drilling():
    # Even if a tall spec slips through, the hole loop is capped.
    from woodworking_ai.drilling import _pin_heights
    assert len(_pin_heights(10**9)) <= 400
    assert _pin_heights(float("inf")) == []


def test_nan_dimension_never_reaches_json():
    res = build_result(base(width=float("nan")), want_png=False, want_glb=False)
    assert res["valid"] is False
    json.dumps(res, allow_nan=False)  # error path is still clean JSON


# --- bad enums / malformed specs ----------------------------------------

def test_unknown_cabinet_type_raises():
    with pytest.raises(ValueError):
        CabinetSpec.from_dict({"cabinet_type": "spaceship", "width": 600})


def test_unknown_construction_raises():
    with pytest.raises(ValueError):
        CabinetSpec.from_dict({"construction": "welded", "width": 600})


def test_from_dict_tolerates_extra_and_missing_keys():
    spec = CabinetSpec.from_dict({"width": 700, "nonsense": 1, "name": "X"})
    assert spec.width == 700 and spec.name == "X"


# --- web API error paths -------------------------------------------------

def test_web_rejects_invalid_export():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from woodworking_ai.web import app
    c = TestClient(app)
    # Invalid spec → 422 from the export endpoint (validated up front).
    r = c.post("/api/export/cutlist", json={"spec": {"cabinet_type": "base",
                                                     "width": -1}})
    assert r.status_code == 422
    # Malformed enum → 400 from spec parsing.
    r = c.post("/api/build", json={"spec": {"cabinet_type": "nope"}})
    assert r.status_code == 400
