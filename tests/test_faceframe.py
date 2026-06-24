"""Tests for face-frame construction (no CAD / API key)."""

import pytest

from woodworking_ai import (
    CabinetSpec, Construction, Material, ToeKick, Drawer,
    generate_cutlist, validate,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique


def ff(**o) -> CabinetSpec:
    d = dict(name="FF Base", construction=Construction.FACE_FRAME,
             width=600, height=720, depth=560, material=Material(18, 6, 18, 18),
             toe_kick=ToeKick(100, 50), shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


def frameless(**o) -> CabinetSpec:
    d = dict(name="Frameless", width=600, height=720, depth=560,
             material=Material(18, 6, 18, 18), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3)
    d.update(o)
    return CabinetSpec(**d)


# --- frame parts ---------------------------------------------------------

def test_face_frame_adds_stiles_and_rails():
    labels = {p.label for p in panel_layout(ff())}
    assert {"Stile L", "Stile R", "Rail top", "Rail bottom"} <= labels


def test_frameless_has_no_frame_parts():
    labels = {p.label for p in panel_layout(frameless())}
    assert not any(l.startswith(("Stile", "Rail")) for l in labels)


def test_cutlist_lists_frame_in_solid_hardwood():
    cl = generate_cutlist(ff())
    frame = [p for p in cl.parts if p.material == "frame"]
    assert {p.name for p in frame} == {"Face-frame stile", "Face-frame rail"}
    assert all(p.thickness == 19 for p in frame)


# --- inset fronts are smaller than overlay -------------------------------

def test_inset_doors_narrower_than_overlay():
    ff_door = next(p for p in generate_cutlist(ff()).parts if p.name == "Door")
    ov_door = next(p for p in generate_cutlist(frameless()).parts if p.name == "Door")
    # Inset doors fit inside the frame opening, so they are narrower.
    assert ff_door.width < ov_door.width


def test_door_notes_say_inset():
    door = next(p for p in generate_cutlist(ff()).parts if p.name == "Door")
    assert "inset" in door.notes


# --- geometry soundness --------------------------------------------------

def test_face_frame_has_no_interferences():
    for spec in (ff(), ff(doors=1, width=450),
                 ff(doors=0, drawers=[Drawer(140), Drawer(160)]),
                 ff(doors=2, drawers=[Drawer(140)])):
        crit = critique(spec)
        assert crit.report["interference_count"] == 0, spec.name


def test_face_frame_envelope_matches_spec():
    r = critique(ff(width=800, height=900)).report
    assert r["width"] == pytest.approx(800)
    assert r["height"] == pytest.approx(900)


def test_face_frame_validates():
    assert validate(ff()).ok
