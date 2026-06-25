"""Kitchen accessories: countertops, appliance cutouts, fillers, moldings."""

from woodworking_ai.dsl import CabinetSpec
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai.estimator import estimate
from woodworking_ai.accessories import countertop_cutouts
from woodworking_ai.geometry import panel_layout
from woodworking_ai.validator import validate


def _cab(accessories):
    return CabinetSpec(width=900, height=720, depth=560, doors=2, shelves=1,
                       accessories=accessories)


def test_countertop_becomes_a_part_with_overhang():
    cl = generate_cutlist(_cab([
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30}]))
    ct = next(p for p in cl.parts if p.name == "Countertop")
    assert ct.length == 900                    # spans the cabinet width
    assert ct.width == 600 + 30                # depth + overhang
    assert ct.material == "countertop"


def test_filler_and_end_panel_become_parts():
    cl = generate_cutlist(_cab([
        {"kind": "filler", "width": 75, "side": "left"},
        {"kind": "end_panel", "side": "right"}]))
    names = {p.name for p in cl.parts}
    assert "Filler" in names and "End panel" in names


def test_crown_molding_runs_the_width():
    cl = generate_cutlist(_cab([{"kind": "molding", "type": "crown", "height": 90}]))
    crown = next(p for p in cl.parts if "molding" in p.name.lower())
    assert crown.length == 900
    assert crown.material == "molding"


def test_sink_cutout_that_fits_is_valid():
    res = validate(_cab([
        {"kind": "appliance", "type": "sink", "cutout_w": 600, "cutout_d": 450}]))
    assert res.ok


def test_oversized_cutout_is_an_error():
    # Interior is 900 - 2*18 = 864; a 900mm cutout cannot fit.
    res = validate(_cab([
        {"kind": "appliance", "type": "sink", "cutout_w": 900, "cutout_d": 450}]))
    assert not res.ok
    assert any("cutout" in e.message for e in res.errors)


def test_accessory_parts_get_their_own_id_series():
    cl = generate_cutlist(_cab([{"kind": "countertop", "depth": 600}]))
    ct = next(p for p in cl.parts if p.name == "Countertop")
    assert ct.id.startswith("G")


def test_no_accessories_leaves_cabinet_unchanged():
    plain = CabinetSpec(width=900, height=720, depth=560, doors=2, shelves=1)
    assert not any(p.material in ("countertop", "molding")
                   for p in generate_cutlist(plain).parts)


# --- B2: sink/cooktop cut-out subtracted from the countertop -----------------

def _sink_cab():
    return _cab([
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30},
        {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450}])


def test_countertop_cutouts_centred_over_host():
    cuts = countertop_cutouts(_sink_cab())
    assert len(cuts) == 1
    x, y, w, d = cuts[0]
    assert (w, d) == (700.0, 450.0)
    # Centred in the 900-wide × 630-deep blank: corner at ((900-700)/2, (630-450)/2).
    assert x == 100.0 and y == 90.0


def test_no_cutout_without_a_sink_or_cooktop():
    assert countertop_cutouts(_cab([{"kind": "countertop", "depth": 600}])) == []
    # A range is a GAP appliance, not a counter cut-out.
    assert countertop_cutouts(_cab([
        {"kind": "countertop", "depth": 600},
        {"kind": "appliance", "type": "range", "cutout_w": 760}])) == []


def test_countertop_part_carries_the_cutout_and_a_note():
    ct = next(p for p in generate_cutlist(_sink_cab()).parts
              if p.name == "Countertop")
    assert ct.openings == [(100.0, 90.0, 700.0, 450.0)]
    assert "cutout" in ct.notes.lower()


def test_countertop_finishable_area_drops_by_the_cutout():
    ct = next(p for p in generate_cutlist(_sink_cab()).parts
              if p.name == "Countertop")
    gross = (900 / 1000.0) * (630 / 1000.0)
    cut = (700 / 1000.0) * (450 / 1000.0)
    assert abs(ct.area_m2 - (gross - cut)) < 1e-9
    assert ct.area_m2 < gross


def test_estimate_counter_area_drops_by_the_cutout():
    with_cut = estimate(_sink_cab())
    no_cut = estimate(_cab([
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30}]))
    # The finished area (sand + coat) shrinks by the routed-out opening.
    assert with_cut.finish_m2 == 0.0 and no_cut.finish_m2 == 0.0  # no finish set
    cl_cut = generate_cutlist(_sink_cab())
    cl_plain = generate_cutlist(_cab([
        {"kind": "countertop", "depth": 600, "thickness": 38, "overhang": 30}]))
    a_cut = next(p for p in cl_cut.parts if p.name == "Countertop").area_m2
    a_plain = next(p for p in cl_plain.parts if p.name == "Countertop").area_m2
    assert a_cut < a_plain


def test_geometry_countertop_panel_carries_openings():
    panels = panel_layout(_sink_cab())
    ct = next(p for p in panels if p.label == "Countertop")
    assert len(ct.openings) == 1
    ocx, ocy, ow, od = ct.openings[0]
    assert (ow, od) == (700.0, 450.0)
    # Centred in X over the cabinet.
    assert abs(ocx) < 1e-9
