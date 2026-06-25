"""Tests for the wood-species database (H5): lookups, name aliasing, graceful
fallbacks, and species-specific seasonal movement."""

import pytest

from woodworking_ai import species
from woodworking_ai import engineering, materials


# --- lookups -------------------------------------------------------------

def test_get_returns_record_for_known_wood():
    s = species.get("walnut")
    assert s is not None
    assert s.name == "walnut"
    assert s.modulus_mpa > 0
    assert s.janka > 0
    assert s.density_kg_m3 > 0
    assert 0 < s.movement_flatsawn < 0.1


def test_table_has_the_expected_common_woods():
    have = set(species.names())
    for w in ("pine", "poplar", "soft_maple", "hard_maple", "red_oak",
              "white_oak", "ash", "cherry", "walnut", "birch", "mahogany",
              "beech", "hickory", "alder"):
        assert w in have, w
    # ~15 woods plus the generic fallback (excluded from names()).
    assert len(have) >= 14


def test_modulus_janka_density_price_accessors():
    assert species.modulus("white_oak") == species.get("white_oak").modulus_mpa
    assert species.janka("hickory") == species.get("hickory").janka
    assert species.density("pine") == species.get("pine").density_kg_m3
    assert species.price_per_bdft("walnut") == species.get("walnut").price_per_bdft


# --- aliasing ------------------------------------------------------------

def test_aliases_resolve_to_canonical():
    assert species.get("oak").name == "red_oak"
    assert species.get("maple").name == "hard_maple"
    assert species.get("White Oak").name == "white_oak"
    assert species.get("white_oak").name == "white_oak"
    assert species.get("black walnut").name == "walnut"


def test_normalize_is_case_space_and_hyphen_tolerant():
    assert species.normalize("  Hard-Maple ") == "hard_maple"
    assert species.normalize("WHITE OAK") == "white_oak"


# --- fallbacks -----------------------------------------------------------

def test_unknown_or_blank_returns_none():
    assert species.get("unobtanium") is None
    assert species.get("") is None
    assert species.get(None) is None
    assert species.known("oak") and not species.known("unobtanium")


def test_scalar_accessors_none_for_unknown():
    assert species.modulus("unobtanium") is None
    assert species.janka("unobtanium") is None
    assert species.price_per_bdft("unobtanium") is None


def test_text_notes_fall_back_to_generic():
    # finishing/workability degrade to the generic record, never crash.
    assert species.finishing_note("unobtanium") == species.GENERIC.finishing
    assert species.workability_note("") == species.GENERIC.workability
    assert isinstance(species.finishing_note("walnut"), str)


# --- movement differs by species -----------------------------------------

def test_movement_differs_by_species():
    # Walnut is one of the most stable woods; white oak moves clearly more.
    assert species.movement_fraction("walnut") < \
        species.movement_fraction("white_oak")


def test_quartersawn_is_half_of_flatsawn_per_species():
    flat = species.movement_fraction("hard_maple", "flatsawn")
    quarter = species.movement_fraction("hard_maple", "quartersawn")
    assert quarter == pytest.approx(flat / 2, rel=1e-9)


def test_movement_fraction_unknown_uses_generic():
    assert species.movement_fraction("unobtanium") == \
        pytest.approx(species.GENERIC.movement_flatsawn)


# --- finishing categories ------------------------------------------------

def test_finishing_categories():
    assert species.finishing_category("cherry") == species.FINISH_BLOTCH
    assert species.finishing_category("hard_maple") == species.FINISH_BLOTCH
    assert species.finishing_category("walnut") == species.FINISH_OILY
    assert species.finishing_category("white_oak") == species.FINISH_OPEN_PORE
    assert species.finishing_category("unobtanium") is None


# --- integration: engineering defers to the species DB -------------------

def test_engineering_modulus_uses_species_db():
    assert engineering.modulus_for("white_oak") == species.modulus("white_oak")
    # Sheet goods aren't woods — they still resolve via the local fallback map.
    assert engineering.modulus_for("mdf") == engineering.MODULUS_MPA["mdf"]
    # Unknown still defaults to plywood, as before.
    assert engineering.modulus_for("unobtanium") == engineering.DEFAULT_MODULUS


def test_engineering_seasonal_movement_species_specific():
    width = 800.0
    walnut = engineering.seasonal_movement(width, "flatsawn", species="walnut")
    oak = engineering.seasonal_movement(width, "flatsawn", species="white_oak")
    assert walnut < oak
    # No species -> the global flatsawn constant (back-compat default).
    glob = engineering.seasonal_movement(width, "flatsawn")
    assert glob == pytest.approx(width * engineering.MOVEMENT_FLATSAWN)
    # An unknown species also falls back to the global constant.
    assert engineering.seasonal_movement(width, "flatsawn", species="unobtanium") \
        == pytest.approx(glob)


# --- integration: species-aware finishing advisories ---------------------

def test_species_finishing_hints_by_category():
    blotch = materials.species_finishing_hints({"Cherry"})
    assert any("conditioner" in m.lower() for _, _, m in blotch)
    oily = materials.species_finishing_hints({"Walnut"})
    assert any("oily" in m.lower() and "solvent" in m.lower()
               for _, _, m in oily)
    pore = materials.species_finishing_hints({"White Oak"})
    assert any("pore" in m.lower() for _, _, m in pore)
    # Easy/unknown woods add no special finishing hint.
    assert materials.species_finishing_hints({"unobtanium"}) == []
