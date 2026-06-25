"""Kitchen accessories: countertops, appliance cutouts, fillers, moldings."""

from woodworking_ai.dsl import CabinetSpec
from woodworking_ai.cutlist import generate_cutlist
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
