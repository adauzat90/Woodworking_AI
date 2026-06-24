"""Tests for the center mullion (frameless post / face-frame center stile)."""


from woodworking_ai import (
    CabinetSpec, Construction, Material, ToeKick, generate_cutlist, validate,
)
from woodworking_ai.geometry import panel_layout
from woodworking_ai.agents.critic import critique


def base(**o) -> CabinetSpec:
    d = dict(name="Mull", width=800, height=720, depth=560,
             material=Material(18, 6, 18, 18, 12), toe_kick=ToeKick(100, 50),
             shelves=1, doors=2, drawers=[], reveal=3, center_mullion=True)
    d.update(o)
    return CabinetSpec(**d)


def test_frameless_mullion_part_present():
    cl = generate_cutlist(base())
    assert "Mullion" in {p.name for p in cl.parts}


def test_face_frame_center_stile_present():
    cl = generate_cutlist(base(construction=Construction.FACE_FRAME))
    assert "Face-frame center stile" in {p.name for p in cl.parts}


def test_mullion_narrows_each_door():
    with_m = next(p for p in generate_cutlist(base()).parts if p.name == "Door")
    without = next(p for p in generate_cutlist(base(center_mullion=False)).parts
                   if p.name == "Door")
    assert with_m.width < without.width


def test_mullion_in_geometry():
    labels = {p.label for p in panel_layout(base())}
    assert "Mullion" in labels


def test_mullion_no_interference():
    for spec in (base(), base(construction=Construction.FACE_FRAME),
                 base(width=900, drawers=[])):
        assert critique(spec).report["interference_count"] == 0, spec.name


def test_mullion_on_single_door_warns():
    assert any(w.field == "center_mullion"
               for w in validate(base(doors=1, width=450)).warnings)


def test_no_mullion_when_flag_false():
    assert "Mullion" not in {p.label for p in panel_layout(base(center_mullion=False))}
