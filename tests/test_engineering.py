"""Tests for the structural/material engineering checks added to the validator:
shelf sag, tip-over, KCMA toe kick, and solid-top wood movement."""

import pytest

from woodworking_ai import (
    CabinetSpec, CabinetType, Material, ToeKick, Drawer, TableSpec, validate,
    engineering,
)


# --- pure engineering functions -----------------------------------------

def test_deflection_grows_with_span_cubed_plus():
    """Deflection scales with L^4 — doubling the span multiplies sag ~16x."""
    base = engineering.shelf_deflection(600, 250, 18, 0.2, 10300)
    wide = engineering.shelf_deflection(1200, 250, 18, 0.2, 10300)
    assert wide / base == pytest.approx(16.0, rel=0.01)


def test_thicker_shelf_sags_far_less():
    thin = engineering.shelf_deflection(800, 250, 12, 0.2, 10300)
    thick = engineering.shelf_deflection(800, 250, 24, 0.2, 10300)
    # thickness enters as h^3 -> 2x thickness => 1/8 the sag.
    assert thick / thin == pytest.approx(1 / 8, rel=0.01)


def test_stiffer_species_sags_less():
    ply = engineering.evaluate_shelf(900, 250, 18, 30, "plywood")
    mdf = engineering.evaluate_shelf(900, 250, 18, 30, "mdf")
    assert mdf.deflection > ply.deflection


def test_unknown_species_defaults_to_plywood():
    assert engineering.modulus_for("unobtanium") == engineering.DEFAULT_MODULUS


def test_quartersawn_moves_half_of_flatsawn():
    flat = engineering.seasonal_movement(300, "flatsawn")
    quarter = engineering.seasonal_movement(300, "quartersawn")
    assert quarter == pytest.approx(flat / 2, rel=1e-6)


def test_tip_factor_lower_for_tall_shallow():
    assert engineering.tip_safety_factor(2000, 300) < \
        engineering.tip_safety_factor(800, 500)


# --- species database wired into engineering (H5) ------------------------

def test_modulus_for_defers_to_species_db():
    from woodworking_ai import species
    # A known wood reads from the one species table.
    assert engineering.modulus_for("white_oak") == species.modulus("white_oak")
    # Aliases resolve too ("oak" -> red_oak).
    assert engineering.modulus_for("oak") == species.modulus("oak")
    # Sheet goods (not woods) still use the local fallback map.
    assert engineering.modulus_for("plywood") == engineering.MODULUS_MPA["plywood"]


def test_seasonal_movement_species_specific_and_backcompat():
    # Stable walnut moves less across the grain than white oak for the same width.
    assert engineering.seasonal_movement(800, "flatsawn", species="walnut") < \
        engineering.seasonal_movement(800, "flatsawn", species="white_oak")
    # Default (no species) is unchanged: the global flatsawn constant.
    assert engineering.seasonal_movement(300, "flatsawn") == \
        pytest.approx(300 * engineering.MOVEMENT_FLATSAWN)
    # Quartersawn still halves the species value.
    flat = engineering.seasonal_movement(300, "flatsawn", species="hard_maple")
    quarter = engineering.seasonal_movement(300, "quartersawn", species="hard_maple")
    assert quarter == pytest.approx(flat / 2, rel=1e-6)


# --- shelf sag wired into the validator (STRUCT-020..022) ----------------

def _shelf_cabinet(**o) -> CabinetSpec:
    d = dict(name="BC", cabinet_type=CabinetType.BOOKCASE, width=800,
             height=1800, depth=300, shelves=1, doors=0,
             toe_kick=ToeKick(80, 50))
    d.update(o)
    return CabinetSpec(**d)


def test_long_thin_particleboard_shelf_fails():
    spec = _shelf_cabinet(width=1400, shelf_species="particleboard",
                          material=Material(shelf=15), shelf_load_kg_per_m=40)
    result = validate(spec)
    assert not result.ok
    assert any(e.field == "shelves" for e in result.errors)


def test_modest_plywood_shelf_passes():
    assert validate(_shelf_cabinet(width=700)).ok


def test_shelf_status_thresholds():
    """Sag below the visible limit is ok; between visible and span/360 is a
    warning band; beyond span/360 fails."""
    span = 1000.0
    eng = span * engineering.DEFLECTION_ENGINEERING      # ≈ 2.78mm
    vis = span * engineering.DEFLECTION_VISIBLE           # ≈ 2.60mm
    assert vis < eng
    mk = lambda d: engineering.ShelfResult(d, span, eng, vis)
    assert mk(vis - 0.1).status == "ok"
    assert mk((vis + eng) / 2).status == "visible"
    assert mk(eng + 0.1).status == "fail"


# --- tip-over (STRUCT-030/031, ASTM F2057) -------------------------------

def test_tall_dresser_without_anti_tip_warns():
    dr = CabinetSpec(name="DR", cabinet_type=CabinetType.DRESSER, width=800,
                     height=1100, depth=500, shelves=0, doors=0,
                     drawers=[Drawer(180)] * 5, toe_kick=ToeKick(80, 50))
    r = validate(dr)
    assert r.ok  # advisory, not a hard error
    assert any(w.field == "anti_tip" for w in r.warnings)


def test_anti_tip_flag_silences_the_warning():
    dr = CabinetSpec(name="DR", cabinet_type=CabinetType.DRESSER, width=800,
                     height=1100, depth=500, shelves=0, doors=0,
                     drawers=[Drawer(180)] * 5, toe_kick=ToeKick(80, 50),
                     anti_tip=True)
    assert not any(w.field == "anti_tip" for w in validate(dr).warnings)


def test_short_dresser_below_f2057_scope_no_warning():
    dr = CabinetSpec(name="DR", cabinet_type=CabinetType.DRESSER, width=900,
                     height=600, depth=500, shelves=0, doors=0,
                     drawers=[Drawer(180)] * 2, toe_kick=ToeKick(80, 50))
    assert not any(w.field == "anti_tip" for w in validate(dr).warnings)


def test_tall_and_shallow_flags_tip_risk():
    tall_shallow = CabinetSpec(name="T", cabinet_type=CabinetType.TALL,
                               width=600, height=2100, depth=300, shelves=5,
                               doors=2, toe_kick=ToeKick(100, 50), anti_tip=True)
    assert any(w.field == "depth" for w in validate(tall_shallow).warnings)


# --- KCMA toe kick minimum (STRUCT-042) ----------------------------------

def test_shallow_toe_kick_warns():
    spec = CabinetSpec(name="B", width=600, height=720, depth=560,
                       toe_kick=ToeKick(height=60, setback=40))
    fields = {w.field for w in validate(spec).warnings}
    assert "toe_kick.height" in fields
    assert "toe_kick.setback" in fields


def test_standard_toe_kick_ok():
    spec = CabinetSpec(name="B", width=600, height=720, depth=560,
                       toe_kick=ToeKick(height=100, setback=50))
    assert not any(w.field.startswith("toe_kick.") for w in validate(spec).warnings)


# --- solid-top wood movement (MOVE-001/002) ------------------------------

def _table(**o) -> TableSpec:
    d = dict(name="T", width=1400, depth=800, height=740, leg=60,
             apron_height=90, top_thickness=25, leg_inset=40)
    d.update(o)
    return TableSpec(**d)


def test_fixed_solid_top_is_an_error():
    r = validate(_table(solid_top=True, top_fixing="fixed"))
    assert not r.ok
    assert any(e.field == "top_fixing" for e in r.errors)


def test_floating_solid_top_warns_with_allowance():
    r = validate(_table(solid_top=True, top_fixing="floating", depth=800))
    assert r.ok
    assert any(w.field == "top_fixing" for w in r.warnings)


def test_sheet_top_fixed_is_fine():
    # Plywood/MDF top doesn't move; fixing it is acceptable.
    r = validate(_table(solid_top=False, top_fixing="fixed"))
    assert r.ok
    assert not any(i.field == "top_fixing" for i in r.issues)


def test_quartersawn_narrow_top_no_warning():
    r = validate(_table(depth=250, grain="quartersawn", top_fixing="floating"))
    assert not any(w.field == "top_fixing" for w in r.warnings)
