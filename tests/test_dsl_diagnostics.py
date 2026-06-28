"""Tier-1 DSL diagnostics improvements: rule IDs, the Severity enum, the
species->stiffness silent-fallback warning (MAT-006/007), and the small
correctness fixes (dead negative-shelf check, MAT-002 sheet unit)."""

from __future__ import annotations

from woodworking_ai import spec_from_dict, validate
from woodworking_ai import engineering
from woodworking_ai.validator import Issue, Severity


def _cab(**kw):
    base = dict(kind="cabinet", cabinet_type="bookcase", width=900, height=1200,
               depth=300, doors=0, shelves=3, toe_kick=None)
    base.update(kw)
    return spec_from_dict(base)


# --- Severity enum ---------------------------------------------------------

def test_severity_enum_compares_equal_to_bare_strings():
    # StrEnum members must equal the legacy strings so .ok/.errors keep working.
    assert Severity.ERROR == "error"
    assert Severity.WARNING == "warning"
    assert Severity.INFO == "info"
    iss = Issue(Severity.ERROR, "f", "m", "X-1")
    assert iss.severity == "error"


def test_issue_str_does_not_leak_rule_id():
    # Rendering is intentionally unchanged; rule_id is programmatic only.
    assert str(Issue(Severity.WARNING, "joinery", "weak", "STRUCT-010")) == \
        "[warning] joinery: weak"
    assert str(Issue(Severity.WARNING, "joinery", "weak")) == \
        "[warning] joinery: weak"


# --- rule_id attachment + by_rule ------------------------------------------

def test_structural_rules_carry_their_catalog_id():
    r = validate(_cab(cabinet_type="base", height=720, depth=560, doors=2,
                      shelves=0, joinery="butt"))
    butt = r.by_rule("STRUCT-010")
    assert butt and butt[0].message  # carcass butt-joint warning is tagged


def test_by_rule_filters_by_stable_id():
    r = validate(_cab(shelf_species="wlnut"))
    assert r.by_rule("MAT-006")
    assert r.by_rule("NOPE-999") == []


# --- MAT-006: unknown shelf species silently computed as plywood -----------

def test_unknown_shelf_species_warns_instead_of_silently_using_plywood():
    r = validate(_cab(shelf_species="wlnut"))   # typo for walnut
    issues = r.by_rule("MAT-006")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].field == "shelf_species"
    assert "plywood" in issues[0].message


def test_known_shelf_species_does_not_warn():
    assert validate(_cab(shelf_species="white_oak")).by_rule("MAT-006") == []
    # sheet goods resolve via the local modulus map, not the species DB
    assert validate(_cab(shelf_species="mdf")).by_rule("MAT-006") == []
    # the default never trips it
    assert validate(_cab()).by_rule("MAT-006") == []


# --- MAT-007: species / shelf_species cooperation --------------------------

def test_solid_piece_with_default_plywood_shelf_gets_an_info():
    r = validate(_cab(species="oak"))   # shelf_species left at the plywood default
    info = r.by_rule("MAT-007")
    assert len(info) == 1
    assert info[0].severity == "info"
    assert "oak" in info[0].message


def test_no_mat007_when_shelf_species_is_set():
    assert validate(_cab(species="oak", shelf_species="oak")).by_rule("MAT-007") == []


# --- engineering.resolve_modulus -------------------------------------------

def test_resolve_modulus_reports_resolution():
    e, ok = engineering.resolve_modulus("white_oak")
    assert ok and e > engineering.DEFAULT_MODULUS
    e, ok = engineering.resolve_modulus("plywood")
    assert ok and e == engineering.MODULUS_MPA["plywood"]
    e, ok = engineering.resolve_modulus("unobtanium")
    assert not ok and e == engineering.DEFAULT_MODULUS
    # blank is "resolved" — using the default is documented, not a typo
    e, ok = engineering.resolve_modulus("")
    assert ok and e == engineering.DEFAULT_MODULUS


def test_evaluate_shelf_surfaces_modulus_and_resolution():
    res = engineering.evaluate_shelf(800, 280, 18, 25, species="wlnut")
    assert res.species_resolved is False
    assert res.modulus == engineering.DEFAULT_MODULUS
    res = engineering.evaluate_shelf(800, 280, 18, 25, species="maple")
    assert res.species_resolved is True


# --- small correctness fixes -----------------------------------------------

def test_negative_shelves_still_errors_after_dead_check_removed():
    # The unreachable `shelves < 0` block was deleted; the int-range check still
    # rejects a negative count.
    r = validate(_cab(shelves=-1))
    assert not r.ok
    assert any(i.field == "shelves" for i in r.errors)


def test_oversize_panel_message_has_sheet_unit():
    r = validate(_cab(cabinet_type="tall", width=3000, height=2400, depth=600,
                      shelves=2))
    msg = " ".join(i.message for i in r.by_rule("MAT-002"))
    assert "2440×1220mm" in msg
