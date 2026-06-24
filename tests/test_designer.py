"""The Designer agent routes its JSON to the right spec type (cabinet/table).

The LLM call is stubbed, so these run without an API key or the SDK.
"""

import json

from woodworking_ai import CabinetSpec, TableSpec
from woodworking_ai.agents import designer
from woodworking_ai.agents import llm


def _stub(monkeypatch, payload: dict):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(payload))


def test_designer_produces_a_table(monkeypatch):
    _stub(monkeypatch, {"kind": "table", "name": "Dining", "width": 1600,
                        "depth": 900, "height": 740, "leg": 70,
                        "apron_height": 90, "top_thickness": 25, "leg_inset": 50})
    res = designer.design_from_prompt("a big dining table")
    assert isinstance(res.spec, TableSpec)
    assert res.validation.ok
    assert res.spec.width == 1600


def test_designer_produces_a_cabinet(monkeypatch):
    _stub(monkeypatch, {"cabinet_type": "base", "name": "Sink", "width": 600,
                        "height": 720, "depth": 560, "doors": 2})
    res = designer.design_from_prompt("a sink base", run_critic=False)
    assert isinstance(res.spec, CabinetSpec)
    assert res.validation.ok


def test_designer_accepts_imperial_output(monkeypatch):
    _stub(monkeypatch, {"cabinet_type": "base", "units": "in",
                        "width": 24, "height": 30, "depth": 24, "doors": 1})
    res = designer.design_from_prompt("a 24 inch base", run_critic=False)
    assert isinstance(res.spec, CabinetSpec)
    assert abs(res.spec.width - 609.6) < 0.1     # normalized to mm
    assert res.spec.units == "mm"
