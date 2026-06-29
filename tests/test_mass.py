"""Weight/liftability diagnostics (Tier 3 #8): mass.py estimation, the HW-007
one-person-lift warning, and the STRUCT-043 wall-cabinet hanging note."""

from __future__ import annotations

from woodworking_ai import spec_from_dict, validate
from woodworking_ai import mass


# --- mass.py unit ----------------------------------------------------------

def test_piece_mass_uses_species_density_for_solid_wood():
    # 1000×200×20mm = 0.004 m^3; maple ≈ 705 kg/m^3 → ~2.82 kg.
    m = mass.piece_mass_kg(1000, 200, 20, form="solid", species_name="maple")
    assert abs(m - 0.004 * 705) < 0.01


def test_piece_mass_uses_sheet_density_for_sheet_goods():
    # A sheet form wins over species (plywood isn't a wood).
    m = mass.piece_mass_kg(1000, 200, 20, form="plywood", species_name="maple")
    assert abs(m - 0.004 * mass.SHEET_DENSITY_KG_M3["plywood"]) < 0.01


def test_piece_mass_falls_back_for_unknown_and_nonpositive():
    assert mass.piece_mass_kg(1000, 200, 20, species_name="unobtanium") > 0
    assert mass.piece_mass_kg(0, 200, 20) == 0.0


def test_estimate_mass_returns_total_and_heaviest():
    spec = spec_from_dict(dict(kind="cabinet", cabinet_type="tall", width=900,
                               height=2400, depth=600, shelves=3, toe_kick=None,
                               material={"carcass": 30}))
    est = mass.estimate_mass(spec)
    assert est is not None
    assert est.total_kg > est.heaviest_part_kg > 0
    assert est.heaviest_part_name


# --- HW-007 one-person lift ------------------------------------------------

def test_hw007_fires_on_a_heavy_single_panel():
    # A 30mm-ply tall-cabinet side panel is ~26kg — past the one-person lift.
    spec = spec_from_dict(dict(kind="cabinet", cabinet_type="tall", width=900,
                               height=2400, depth=600, shelves=3, toe_kick=None,
                               material={"carcass": 30}))
    hw = validate(spec).by_rule("HW-007")
    assert len(hw) == 1
    assert hw[0].severity == "warning"
    assert hw[0].limit == 25.0 and hw[0].observed > hw[0].limit
    assert hw[0].units == "kg" and hw[0].direction == "max"


def test_hw007_catches_a_heavy_glued_up_solid_top():
    # The cut list explodes a wide solid top into light edge-glue staves; HW-007
    # must still see the heavy ASSEMBLED panel a person actually lifts, not the
    # ~8kg stave.
    spec = spec_from_dict(dict(kind="table", width=2200, depth=1100, height=740,
                               top_thickness=40, leg=80, apron_height=100,
                               apron_thickness=25, leg_inset=50, species="oak",
                               material_form="solid", solid_top=True))
    hw = validate(spec).by_rule("HW-007")
    assert len(hw) == 1
    assert hw[0].observed > 25.0 and "Top" in hw[0].message


def test_hw007_quiet_for_normal_stock():
    # A modest base cabinet has no part near the lift limit.
    spec = spec_from_dict(dict(kind="cabinet", cabinet_type="base", width=600,
                               height=720, depth=560, shelves=1, doors=2))
    assert validate(spec).by_rule("HW-007") == []


# --- STRUCT-043 wall-cabinet hanging ---------------------------------------

def test_struct043_notes_wall_cabinet_hanging_load():
    spec = spec_from_dict(dict(kind="cabinet", cabinet_type="wall", width=900,
                               height=700, depth=350, shelves=2))
    s = validate(spec).by_rule("STRUCT-043")
    assert len(s) == 1
    assert s[0].severity == "info"           # never blocks a build
    assert s[0].units == "kg" and s[0].observed > 0
    assert "stud" in s[0].message


def test_struct043_only_wall_cabinets():
    base = spec_from_dict(dict(kind="cabinet", cabinet_type="base", width=900,
                               height=720, depth=560, shelves=2))
    assert validate(base).by_rule("STRUCT-043") == []


def test_mass_advisories_skipped_for_a_broken_spec():
    # A spec with errors has no meaningful cut list — no weight advisories run.
    bad = spec_from_dict(dict(kind="cabinet", cabinet_type="base", width=-1,
                              height=720, depth=560))
    r = validate(bad)
    assert not r.ok
    assert r.by_rule("HW-007") == [] and r.by_rule("STRUCT-043") == []
