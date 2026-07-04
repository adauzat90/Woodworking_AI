"""Generic `piece` (escape hatch) — explicit rectangular parts + joints.

Proves the piece leaf flows through the whole pipeline (validation, cut list,
joinery, cost, geometry) with no edit to any generic stage, and that its generic
physics validator catches the spec bugs the taxonomy kinds can't express.
"""

import pytest

from woodworking_ai import (
    PieceSpec, PiecePart, Joinery,
    validate, generate_cutlist, estimate, spec_from_dict,
)
from woodworking_ai.dsl import MM_PER_IN
from woodworking_ai.dispatch import spec_kind, PIECE
from woodworking_ai.geometry import panel_layout
from woodworking_ai.joinery import joinery_schedule
from woodworking_ai.assembly_steps import assembly_plan
from woodworking_ai.drilling import drilling_schedule
from woodworking_ai import service, furniture


def _shelving(**kw) -> PieceSpec:
    """A clean 2-post / 3-shelf unit: shelves abut the legs, nothing overlaps."""
    base = dict(
        name="Shelving", material_form="plywood", species="birch",
        parts=[
            {"name": "Leg", "at": [0, 0, 0], "size": [38, 400, 1000],
             "grain": "z", "material_form": "solid", "species": "pine",
             "repeat": {"count": 2, "step": [1162, 0, 0]}},
            {"name": "Shelf", "at": [38, 0, 200], "size": [1124, 400, 18],
             "grain": "x", "repeat": {"count": 3, "step": [0, 0, 380]}},
        ],
        joints=[{"parts": ["Leg", "Shelf"], "joinery": "screw"}],
    )
    base.update(kw)
    return PieceSpec(**base)


# --- dispatch / registry ----------------------------------------------------

def test_dispatch_kind_and_registry():
    assert spec_kind(_shelving()) == PIECE
    assert furniture.is_registered(PIECE)


def test_spec_from_dict_routes_piece_and_aliases():
    for kind in ("piece", "custom", "parts"):
        got = spec_from_dict({"kind": kind, "parts": [
            {"name": "P", "at": [0, 0, 0], "size": [10, 10, 10]}]})
        assert isinstance(got, PieceSpec), kind


# --- loader round-trip ------------------------------------------------------

def test_roundtrip_to_from_dict_mm():
    spec = _shelving()
    again = PieceSpec.from_dict(spec.to_dict())
    assert again.to_dict() == spec.to_dict()


def test_imperial_on_load_converts_to_mm():
    spec = PieceSpec.from_dict({
        "kind": "piece", "units": "in", "width": 48,
        "parts": [{"name": "Top", "at": [0, 0, 1], "size": [24, 16, 0.75],
                   "repeat": {"count": 2, "step": [0, 0, 2]}}]})
    assert spec.units == "mm"
    assert spec.width == pytest.approx(48 * MM_PER_IN)
    p = spec.parts[0]
    assert p.at[2] == pytest.approx(1 * MM_PER_IN)
    assert p.size == pytest.approx((24 * MM_PER_IN, 16 * MM_PER_IN, 0.75 * MM_PER_IN))
    assert p.repeat["step"][2] == pytest.approx(2 * MM_PER_IN)


def test_overall_dims_derive_from_bounding_box():
    spec = PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [100, 50, 10]},
        {"name": "B", "at": [200, 0, 0], "size": [100, 50, 300]}])
    assert (spec.width, spec.depth, spec.height) == (300, 50, 300)
    # An explicit non-zero dimension is kept, not overwritten.
    spec2 = PieceSpec(width=1000, parts=[
        {"name": "A", "at": [0, 0, 0], "size": [100, 50, 10]}])
    assert spec2.width == 1000 and spec2.height == 10


# --- repeat expansion -------------------------------------------------------

def test_repeat_expands_named_copies():
    part = PiecePart(name="Slat", at=(0, 0, 0), size=(20, 400, 10),
                     repeat={"count": 3, "step": [30, 0, 0]})
    placed = part.placements()
    assert [n for n, _a, _s in placed] == ["Slat #1", "Slat #2", "Slat #3"]
    assert placed[2][1] == (60, 0, 0)


def test_qty_alias_and_int_shorthand():
    a = PiecePart.from_dict({"name": "P", "at": [0, 0, 0], "size": [1, 1, 1],
                             "qty": {"count": 2, "step": [5, 0, 0]}})
    assert a.count == 2
    b = PiecePart.from_dict({"name": "P", "at": [0, 0, 0], "size": [1, 1, 1],
                             "qty": 4})
    assert b.count == 4


# --- cut-list orientation from grain ---------------------------------------

def test_cut_dims_follow_grain_axis():
    cl = generate_cutlist(PieceSpec(name="X", parts=[
        {"name": "Along-Y", "at": [0, 0, 0], "size": [40, 900, 20], "grain": "y"},
        {"name": "NoGrain", "at": [0, 0, 0], "size": [40, 900, 20]},
    ]))
    along = next(p for p in cl.parts if p.name == "Along-Y")
    # grain runs along Y (900) -> length 900, then width 40, thickness 20.
    assert (along.length, along.width, along.thickness) == (900, 40, 20)
    assert along.grain == "length"
    nog = next(p for p in cl.parts if p.name == "NoGrain")
    # no grain -> length is the longer face dim (900), width the shorter (40).
    assert (nog.length, nog.width, nog.thickness) == (900, 40, 20)
    assert nog.grain == "none"


def test_cutlist_material_label_and_per_part_override():
    cl = generate_cutlist(_shelving())
    legs = [p for p in cl.parts if p.name.startswith("Leg")]
    shelves = [p for p in cl.parts if p.name.startswith("Shelf")]
    assert legs and all(p.material == "solid" and p.form == "solid"
                        and p.species == "pine" for p in legs)
    assert shelves and all(p.material == "sheet" and p.form == "plywood"
                           and p.species == "birch" for p in shelves)
    assert all(p.id for p in cl.parts)


def test_screw_joint_emits_assembly_hardware():
    cl = generate_cutlist(_shelving())
    assert any("screw" in h.name.lower() for h in cl.hardware)
    # A captured (glued) joint adds no fastener.
    cl2 = generate_cutlist(_shelving(
        joints=[{"parts": ["Leg", "Shelf"], "joinery": "dado"}]))
    assert not cl2.hardware


# --- geometry (identity compile) -------------------------------------------

def test_panels_are_identity_placed():
    spec = PieceSpec(parts=[
        {"name": "A", "at": [10, 20, 30], "size": [100, 200, 40]}])
    panels = panel_layout(spec)
    assert len(panels) == 1
    assert panels[0].size == (100, 200, 40)
    assert panels[0].center == (60, 120, 50)   # at + size/2


def test_repeat_makes_one_panel_per_copy():
    spec = _shelving()
    labels = [p.label for p in panel_layout(spec)]
    assert "Leg #1" in labels and "Leg #2" in labels
    assert sum(1 for label in labels if label.startswith("Shelf")) == 3


# --- joinery ----------------------------------------------------------------

def test_joinery_ops_map_each_joint():
    ops = joinery_schedule(_shelving()).ops
    assert len(ops) == 1
    assert "screw" in ops[0].operation.lower()
    assert ops[0].part_id                       # resolves to a real part ID


def test_every_joinery_value_builds():
    for j in Joinery:
        spec = _shelving(joints=[{"parts": ["Leg", "Shelf"], "joinery": j.value}])
        assert validate(spec).ok
        assert joinery_schedule(spec).ops


# --- assembly / cost / drilling flow ---------------------------------------

def test_assembly_uses_default_plan():
    subs = assembly_plan(_shelving()).subassemblies
    assert [s.name for s in subs] == ["Build"]


def test_estimate_and_drilling_flow():
    spec = _shelving()
    assert estimate(spec).total > 0
    assert drilling_schedule(spec).spec_name == spec.name


# --- validate: positive case ------------------------------------------------

def test_validate_clean_piece_passes_without_warnings():
    res = validate(_shelving())
    assert res.ok
    assert not res.warnings


# --- validate: error rules --------------------------------------------------

def test_error_no_parts():
    assert not validate(PieceSpec(parts=[])).ok


def test_error_duplicate_names():
    res = validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [10, 10, 10]},
        {"name": "A", "at": [50, 0, 0], "size": [10, 10, 10]}]))
    assert not res.ok
    assert any("duplicate" in e.message for e in res.errors)


def test_error_non_positive_or_nonfinite_size():
    assert not validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [0, 10, 10]}])).ok
    assert not validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [10, 10]}])).ok   # short -> NaN


def test_error_part_below_floor():
    res = validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, -50], "size": [10, 10, 10]}]))
    assert not res.ok
    assert any("floor" in e.message for e in res.errors)


def test_error_joint_unknown_part():
    res = validate(_shelving(
        joints=[{"parts": ["Leg", "Ghost"], "joinery": "screw"}]))
    assert not res.ok
    assert any("unknown part" in e.message for e in res.errors)


def test_error_joint_parts_dont_touch():
    res = validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [10, 10, 10]},
        {"name": "B", "at": [500, 0, 0], "size": [10, 10, 10]}],
        joints=[{"parts": ["A", "B"], "joinery": "screw"}]))
    assert not res.ok
    assert any("don't touch" in e.message for e in res.errors)


def test_error_joint_part_to_itself():
    res = validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [10, 10, 10]}],
        joints=[{"parts": ["A", "A"], "joinery": "screw"}]))
    assert not res.ok


def test_error_parts_count_cap():
    spec = PieceSpec(parts=[
        {"name": "Row", "at": [0, 0, 0], "size": [10, 10, 10],
         "repeat": {"count": 501, "step": [20, 0, 0]}}])
    assert not validate(spec).ok


# --- validate: warning rules ------------------------------------------------

def test_warn_volume_overlap():
    res = validate(PieceSpec(parts=[
        {"name": "A", "at": [0, 0, 0], "size": [100, 100, 100]},
        {"name": "B", "at": [50, 50, 0], "size": [100, 100, 100]}]))
    assert res.ok                                   # overlap is a warning
    assert any("overlap" in w.message for w in res.warnings)


def test_warn_floating_part():
    res = validate(PieceSpec(parts=[
        {"name": "Ground", "at": [0, 0, 0], "size": [100, 100, 10]},
        {"name": "Floater", "at": [500, 0, 500], "size": [50, 50, 50]}]))
    assert res.ok
    assert any("floats free" in w.message for w in res.warnings)


# --- validate: info (buildability) -----------------------------------------

def test_info_sheet_thickness_not_stocked():
    res = validate(PieceSpec(material_form="plywood", parts=[
        {"name": "Panel", "at": [0, 0, 0], "size": [600, 400, 30]}]))
    assert res.ok
    assert any(i.rule_id == "MAT-001" for i in res.infos)


def test_info_solid_too_thick_for_stock():
    res = validate(PieceSpec(material_form="solid", parts=[
        {"name": "Slab", "at": [0, 0, 0], "size": [600, 400, 90]}]))
    assert res.ok
    assert any(i.rule_id == "MAT-003" for i in res.infos)


# --- end-to-end via the shared service path (as other kinds' tests do) ------

def test_service_assemble_end_to_end():
    asm = service.assemble(_shelving())
    assert asm.validation.ok
    assert asm.critique.ok
    assert asm.cutlist.parts
    assert asm.estimate.total > 0
    # CSV export is the CLI/web path; it must render for a piece.
    assert "Shelf" in asm.cutlist.to_csv()
