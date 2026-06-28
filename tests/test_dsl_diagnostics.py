"""Tier-1 DSL diagnostics improvements: rule IDs, the Severity enum, the
species->stiffness silent-fallback warning (MAT-006/007), and the small
correctness fixes (dead negative-shelf check, MAT-002 sheet unit)."""

from __future__ import annotations

from woodworking_ai import spec_from_dict, validate
from woodworking_ai import engineering
from woodworking_ai.diagnostics import Diagnostic
from woodworking_ai.dsl_lint import LintIssue, lint_spec_dict
from woodworking_ai.service import build_result
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


# --- Tier 2: structured (observed/limit/units/fix) -------------------------

def test_sag_error_carries_observed_limit_units_and_fix():
    # A long, thin, heavily loaded plywood shelf fails the structural limit.
    r = validate(_cab(width=1400, depth=300, shelves=2, shelf_species="plywood",
                      material={"shelf": 12}))
    fail = r.by_rule("STRUCT-020")
    assert fail, "expected a structural sag error"
    iss = fail[0]
    # The machine-actionable record: observed sag past the span/360 limit, in mm,
    # with the remedy split out and a deep link to the principles doc.
    assert iss.observed is not None and iss.limit is not None
    assert iss.observed > iss.limit          # it failed because observed > limit
    assert iss.units == "mm"
    assert iss.fix and "support" in iss.fix
    assert iss.doc_anchor.startswith("design-principles.md#")
    # Rendering is unchanged: the prose still embeds the same numbers.
    assert f"{iss.observed:.1f}mm" in iss.message


def test_observed_and_limit_let_a_machine_decide_severity_without_prose():
    # A pass-margin check the repair loop can compute: visible-sag warning is a
    # smaller exceedance than the structural error.
    r = validate(_cab(width=1100, depth=320, shelves=2, shelf_species="plywood",
                      material={"shelf": 16}))
    for iss in r.by_rule("STRUCT-021"):
        assert iss.observed > iss.limit
        assert iss.units == "mm"


def test_tip_over_warning_carries_numeric_factor():
    r = validate(_cab(cabinet_type="tall", width=600, height=2000, depth=300,
                      shelves=3, anti_tip=True))
    tip = r.by_rule("STRUCT-031")
    assert tip
    assert tip[0].observed is not None and tip[0].limit == 0.40
    assert tip[0].fix


def test_plain_bound_checks_have_no_structured_numbers():
    # A type/range error isn't a measured-vs-limit rule; its structured fields
    # stay empty so consumers can tell "computed" rules from bare checks.
    r = validate(_cab(shelves=-1))
    bad = [i for i in r.errors if i.field == "shelves"]
    assert bad and bad[0].observed is None and bad[0].limit is None


# --- Tier 2: Issue/LintIssue unified under the Diagnostic protocol ----------

def test_issue_and_lintissue_both_satisfy_the_diagnostic_protocol():
    iss = Issue(Severity.WARNING, "f", "m", "STRUCT-010")
    lint = lint_spec_dict({"cabinet_type": "base", "hieght": 720})[0]
    assert isinstance(iss, Diagnostic)
    assert isinstance(lint, Diagnostic)


def test_lintissue_exposes_severity_field_and_rule_id():
    lint = lint_spec_dict({"cabinet_type": "base", "hieght": 720})[0]
    assert lint.severity == "warning"          # a dropped key never hard-fails
    assert lint.field == lint.path             # field aliases the dotted path
    assert lint.rule_id == "LINT-001"
    # Rendering is unchanged: bare message, no "[warning] field:" prefix.
    assert str(lint) == lint.message


def test_lintissue_str_and_path_key_unchanged():
    lint = LintIssue("a.b", "b", "ignored unknown field 'b'")
    assert str(lint) == "ignored unknown field 'b'"
    assert (lint.path, lint.key) == ("a.b", "b")


# --- Tier 2: the service bundle exposes the structured fields ---------------

def test_build_result_serialises_structured_fields_when_present():
    spec = _cab(width=1400, depth=300, shelves=2, shelf_species="plywood",
                material={"shelf": 12})
    bundle = build_result(spec, want_png=False, want_glb=False)
    sag = [e for e in bundle["errors"] if e.get("rule_id") == "STRUCT-020"]
    assert sag, "the sag error should be serialised with its rule_id"
    e = sag[0]
    assert e["units"] == "mm" and "fix" in e
    assert e["observed"] > e["limit"]


def test_build_result_omits_empty_structured_fields():
    # A bare type/range error carries no observed/limit/fix — the dict stays slim.
    spec = _cab(shelves=-1)
    bundle = build_result(spec, want_png=False, want_glb=False)
    shelf_errs = [e for e in bundle["errors"] if e["field"] == "shelves"]
    assert shelf_errs
    assert "observed" not in shelf_errs[0] and "fix" not in shelf_errs[0]
