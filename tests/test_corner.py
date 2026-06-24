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


# --- diagonal corner -----------------------------------------------------

def diagonal(**o) -> CabinetSpec:
    d = dict(name="Diag", cabinet_type=CabinetType.CORNER_DIAGONAL, width=900,
             height=720, depth=900, material=Material(18, 6, 18, 18, 12),
             toe_kick=ToeKick(100, 50), shelves=2, doors=1, corner_cut=450,
             reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def test_diagonal_has_angled_door():
    door = next(p for p in panel_layout(diagonal()) if p.label == "Door")
    assert door.rot_z == 45.0
    assert door.is_rotated


def test_diagonal_envelope_matches_footprint():
    r = critique(diagonal()).report
    assert r["width"] == pytest.approx(900)
    assert r["depth"] == pytest.approx(900)
    assert r["height"] == pytest.approx(720)


def test_diagonal_no_aabb_interference():
    # Trim-to-fit blanks and the rotated door are excluded from the AABB test.
    assert critique(diagonal()).report["interference_count"] == 0


def test_diagonal_oversized_blanks_flagged():
    over = {p.label for p in panel_layout(diagonal()) if p.oversized}
    assert "Bottom" in over and "Top" in over


def test_diagonal_cutlist_parts():
    names = {p.name for p in generate_cutlist(diagonal()).parts}
    assert {"Side L", "Side R", "Door", "Corner shelf"} <= names


def test_diagonal_requires_corner_cut():
    assert not validate(diagonal(corner_cut=0)).ok


def test_diagonal_corner_cut_too_big_fails():
    assert not validate(diagonal(corner_cut=900)).ok


def test_diagonal_real_brep_is_clean():
    pytest.importorskip("build123d")
    crit = critique(diagonal(), use_cad=True, brep=True)
    assert crit.ok
    assert crit.report["brep_interference_count"] == 0
