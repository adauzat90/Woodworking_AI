"""The Designer agent routes its JSON to the right spec type (cabinet/table).

The LLM call is stubbed, so these run without an API key or the SDK.
"""

import json

from woodworking_ai import CabinetSpec, TableSpec
from woodworking_ai.agents import designer
from woodworking_ai.agents import llm


def _stub(monkeypatch, payload: dict):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(payload))


def _stub_sequence(monkeypatch, payloads: list[dict]):
    """Return each payload in turn on successive llm.complete calls."""
    calls = {"n": 0}

    def fake(*a, **k):
        i = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        return json.dumps(payloads[i])

    monkeypatch.setattr(llm, "complete", fake)
    return calls


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


def test_designer_repairs_a_dropped_field(monkeypatch):
    # Attempt 1 misspells "height"; the loop must feed that back and accept the
    # corrected spec on attempt 2.
    typo = {"cabinet_type": "base", "name": "Sink", "width": 600,
            "hieght": 720, "depth": 560, "doors": 2}
    fixed = {"cabinet_type": "base", "name": "Sink", "width": 600,
             "height": 720, "depth": 560, "doors": 2}
    calls = _stub_sequence(monkeypatch, [typo, fixed])
    res = designer.design_from_prompt("a sink base", run_critic=False)
    assert calls["n"] == 2                       # it did not stop on attempt 1
    assert res.attempts == 2
    assert res.spec.height == 720


def test_designer_does_not_loop_on_a_clean_spec(monkeypatch):
    clean = {"cabinet_type": "base", "name": "Sink", "width": 600,
             "height": 720, "depth": 560, "doors": 2}
    calls = _stub_sequence(monkeypatch, [clean])
    designer.design_from_prompt("a sink base", run_critic=False)
    assert calls["n"] == 1                        # accepted immediately


def test_designer_returns_best_effort_when_typo_persists(monkeypatch):
    typo = {"cabinet_type": "base", "width": 600, "height": 720,
            "depth": 560, "doors": 2, "hieght": 999}
    _stub(monkeypatch, typo)                      # never corrects
    res = designer.design_from_prompt("a sink base", run_critic=False,
                                      max_attempts=2)
    # Non-fatal: we still return a buildable spec rather than raising.
    assert res.validation.ok
    assert res.attempts == 2


def test_designer_accepts_imperial_output(monkeypatch):
    _stub(monkeypatch, {"cabinet_type": "base", "units": "in",
                        "width": 24, "height": 30, "depth": 24, "doors": 1})
    res = designer.design_from_prompt("a 24 inch base", run_critic=False)
    assert isinstance(res.spec, CabinetSpec)
    assert abs(res.spec.width - 609.6) < 0.1     # normalized to mm
    assert res.spec.units == "mm"


def test_designer_captures_design_notes(monkeypatch):
    # The agent may add a top-level "design_notes" array describing assumptions /
    # changes; it is captured into DesignResult.notes and stripped from the spec.
    _stub(monkeypatch, {
        "cabinet_type": "base", "name": "Sink", "width": 600, "height": 720,
        "depth": 560, "doors": 2,
        "design_notes": ["Assumed frameless construction (most common).",
                         "Picked 18mm birch ply for the carcass."],
    })
    res = designer.design_from_prompt("a sink base", run_critic=False)
    assert res.notes == ["Assumed frameless construction (most common).",
                         "Picked 18mm birch ply for the carcass."]
    # The metadata key never reaches the spec, and was not flagged as a dropped
    # field (so the agent isn't asked to "repair" it) — accepted on attempt 1.
    assert not hasattr(res.spec, "design_notes")
    assert res.validation.ok and res.attempts == 1


def test_design_notes_default_empty(monkeypatch):
    _stub(monkeypatch, {"cabinet_type": "base", "name": "Sink", "width": 600,
                        "height": 720, "depth": 560, "doors": 2})
    res = designer.design_from_prompt("a sink base", run_critic=False)
    assert res.notes == []


def test_design_notes_string_is_coerced(monkeypatch):
    _stub(monkeypatch, {"cabinet_type": "base", "name": "S", "width": 600,
                        "height": 720, "depth": 560, "doors": 2,
                        "design_notes": "Split nothing; followed the request."})
    res = designer.design_from_prompt("a sink base", run_critic=False)
    assert res.notes == ["Split nothing; followed the request."]
