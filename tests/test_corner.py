"""Tests for corner cabinets (blind; diagonal added with rotation support)."""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, validate, generate_cutlist,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique


def blind(**o) -> CabinetSpec:
    d = dict(name="Blind", cabinet_type=CabinetType.CORNER_BLIND, width=900,
             height=720, depth=600, material=Material(18, 6, 18, 18, 12),
             toe_kick=ToeKick(100, 50), shelves=1, doors=1, blind_width=350,
             reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def test_blind_filler_panel_present():
    assert "Blind filler" in {p.label for p in panel_layout(blind())}
    assert "Blind filler" in {p.name for p in generate_cutlist(blind()).parts}


def test_blind_opening_is_offset_to_one_side():
    panels = {p.label: p for p in panel_layout(blind())}
    door_x = panels["Door"].center[0]
    filler_x = panels["Blind filler"].center[0]
    # Door sits to the right of centre; filler to the left.
    assert door_x > 0 > filler_x


def test_blind_door_narrower_than_full_width_door():
    blind_door = next(p for p in generate_cutlist(blind()).parts if p.name == "Door")
    full = blind(cabinet_type=CabinetType.BASE, blind_width=0)
    full_door = next(p for p in generate_cutlist(full).parts if p.name == "Door")
    assert blind_door.width < full_door.width


def test_blind_corner_no_interference_and_full_envelope():
    crit = critique(blind())
    assert crit.report["interference_count"] == 0
    assert crit.report["width"] == pytest.approx(900)


def test_blind_requires_positive_blind_width():
    assert not validate(blind(blind_width=0)).ok


def test_blind_width_too_large_fails():
    assert not validate(blind(blind_width=850)).ok


def test_blind_roundtrips():
    s = blind()
    r = CabinetSpec.from_json(s.to_json())
    assert r.cabinet_type == CabinetType.CORNER_BLIND
    assert r.blind_width == 350
