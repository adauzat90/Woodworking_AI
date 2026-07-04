"""Construction / dimensional lumber support: the 2x4/4x4 catalogue, the SPF and
Douglas-fir species, rectangular (leg_depth) legs, stick-based purchasing, and the
dimensional validator advisory. Pure math, no deps."""

import math

import pytest

from woodworking_ai import (
    estimate, purchase_order, validate, generate_cutlist, stock, species,
    PriceBook,
)
from woodworking_ai.estimator import _ffd_stick_count, _nest_sticks
from woodworking_ai.dsl import (
    TableSpec, BenchSpec, WorkbenchSpec, NightstandSpec, DeskSpec, leg_section,
)


# --- dimensional catalogue -------------------------------------------------

def test_dimensional_match_both_orientations():
    assert stock.dimensional_match(38, 89) == "2x4"
    assert stock.dimensional_match(89, 38) == "2x4"      # orientation-agnostic
    assert stock.dimensional_match(19, 38) == "1x2"
    assert stock.dimensional_match(89, 89) == "4x4"
    assert stock.dimensional_match(140, 140) == "6x6"
    assert stock.dimensional_match(38, 140) == "2x6"


def test_dimensional_match_tolerance():
    # Within the default 1.5mm tolerance still matches; beyond it does not.
    assert stock.dimensional_match(39, 90) == "2x4"
    assert stock.dimensional_match(40, 40) is None       # 2mm off a 2x2
    # A wider explicit tolerance catches the near-miss.
    assert stock.dimensional_match(40, 40, tol=2.0) == "2x2"


def test_nearest_dimensional_suggestion():
    assert stock.nearest_dimensional(90, 40) == "2x4"
    assert stock.nearest_dimensional(88, 88) == "4x4"
    assert stock.nearest_dimensional(140, 140) == "6x6"


def test_standard_lengths_and_labels():
    assert 2438.0 in stock.DIMENSIONAL_LENGTHS_MM     # 8ft
    assert stock.DIMENSIONAL_LENGTH_LABELS[2438.0] == "8ft"
    assert stock.DIMENSIONAL_LENGTH_LABELS[2353.0] == "92-5/8in stud"


# --- species ---------------------------------------------------------------

def test_spf_and_douglas_fir_records():
    spf = species.get("spf")
    assert spf is not None and spf.name == "spf"
    assert spf.price_per_bdft == pytest.approx(0.75)
    df = species.get("douglas_fir")
    assert df is not None and df.modulus_mpa == pytest.approx(13400.0)
    # Douglas fir is genuinely stiffer than yard pine (matters for bench spans).
    assert df.modulus_mpa > species.get("pine").modulus_mpa


def test_construction_aliases_repoint():
    assert species.get("fir").name == "douglas_fir"
    assert species.get("doug_fir").name == "douglas_fir"
    assert species.get("spruce").name == "spf"
    assert species.get("whitewood").name == "spf"
    assert species.get("stud").name == "spf"
    assert species.get("softwood").name == "spf"


# --- leg_depth geometry / cut list -----------------------------------------

def _leg_part(spec):
    return next(p for p in generate_cutlist(spec).parts if p.name == "Leg")


def test_square_leg_default_unchanged():
    spec = TableSpec()
    assert leg_section(spec) == (spec.leg, spec.leg)
    leg = _leg_part(spec)
    assert leg.width == leg.thickness == spec.leg
    assert leg.notes == "square stock"
    # leg_depth == 0 must be byte-identical to a plain square leg.
    assert generate_cutlist(TableSpec(leg=60, leg_depth=0)).parts[1] == \
        generate_cutlist(TableSpec(leg=60)).parts[1]


def test_rectangular_leg_cutlist_and_aprons():
    spec = TableSpec(leg=38, leg_depth=89)   # a 2x4 leg, wide face along depth
    leg = _leg_part(spec)
    assert (leg.width, leg.thickness) == (89, 38)
    assert "89×38" in leg.notes and "depth" in leg.notes
    parts = {p.name: p for p in generate_cutlist(spec).parts}
    # apron_x uses the X-face (38); apron_y uses the Y-face (89).
    assert parts["Apron (long)"].length == pytest.approx(1200 - 80 - 2 * 38)
    assert parts["Apron (short)"].length == pytest.approx(750 - 80 - 2 * 89)


def test_rectangular_leg_is_a_stock_2x4_section():
    leg = _leg_part(TableSpec(leg=38, leg_depth=89))
    assert stock.dimensional_match(leg.thickness, leg.width) == "2x4"


def test_bench_stretcher_tracks_rectangular_leg():
    sq = generate_cutlist(BenchSpec(leg=45))
    rect = generate_cutlist(BenchSpec(leg=38, leg_depth=89))
    slen = lambda cl: next(p.length for p in cl.parts if p.name == "Stretcher")
    # The long stretcher runs along X (uses the X-face 38 vs the square 45), so a
    # narrower X-face lengthens it.
    assert slen(rect) > slen(sq)


def test_all_legged_types_accept_leg_depth():
    for spec in (TableSpec(leg=38, leg_depth=89),
                 BenchSpec(leg=38, leg_depth=89),
                 WorkbenchSpec(leg=38, leg_depth=140),
                 NightstandSpec(leg=38, leg_depth=64),
                 DeskSpec(leg=38, leg_depth=89)):
        leg = _leg_part(spec)
        assert {leg.width, leg.thickness} == {spec.leg, spec.leg_depth}


# --- stick nesting math ----------------------------------------------------

def test_ffd_stick_count_kerf_and_packing():
    # Four ~825mm legs fit one 12ft (3658mm) stick (4*828 = 3312 <= 3658).
    assert _ffd_stick_count([825, 825, 825, 825], 3658, 3.0) == 1
    # Two 1200mm pieces + kerf fit one 8ft stick (2*1203 = 2406 <= 2438).
    assert _ffd_stick_count([1200, 1200], 2438, 3.0) == 1
    # A third 1200 needs a second stick.
    assert _ffd_stick_count([1200, 1200, 1200], 2438, 3.0) == 2


def test_nest_sticks_picks_cheapest_length():
    prices = PriceBook()
    # Four 825mm 2x4 pieces: one 12ft ($6.20) beats two 8ft (2*$3.50 = $7.00).
    sg = _nest_sticks("2x4", "spf", [825] * 4, prices, 3.0)
    assert sg.nominal == "2x4" and sg.sticks == 1
    assert sg.length_label == "12ft"
    assert sg.cost == pytest.approx(6.20)


def test_nest_sticks_none_when_too_long():
    # Longer than the 16ft (4877mm) max stick -> not stickable.
    assert _nest_sticks("2x4", "spf", [5000], PriceBook(), 3.0) is None


# --- estimator + PO with stick pricing -------------------------------------

def test_construction_bench_prices_legs_as_sticks():
    spec = BenchSpec(species="spf", leg=38, leg_depth=89)   # 2x4 legs
    est = estimate(spec)
    assert est.stick_groups, "expected the 2x4 legs priced as sticks"
    sg = next(g for g in est.stick_groups if g.nominal == "2x4")
    assert sg.species == "spf" and sg.sticks >= 1
    assert est.stick_cost > 0


def test_no_milling_waste_on_sticks():
    # A stick group's cost is exactly sticks x the price-book stick price — no
    # 15% lumber-waste multiplier (S4S stock is already surfaced).
    spec = WorkbenchSpec(species="spf", leg=89, leg_depth=89)   # 4x4 legs
    est = estimate(spec)
    sg = next(g for g in est.stick_groups if g.nominal == "4x4")
    assert sg.cost == pytest.approx(sg.sticks * sg.unit_price)
    assert sg.unit_price in PriceBook().stick_prices["4x4"].values()


def test_hardwood_species_still_board_feet():
    # A non-construction species with a dimensional section is NOT stick-priced.
    spec = BenchSpec(species="walnut", leg=38, leg_depth=89)
    est = estimate(spec)
    assert est.stick_groups == []
    assert est.lumber_cost > 0


def test_po_reconciles_with_stick_pricing():
    spec = WorkbenchSpec(species="spf", leg=38, leg_depth=89)
    est = estimate(spec)
    po = purchase_order(spec, est=est)
    assert po.grand_total == pytest.approx(est.total, abs=0.005)
    # A stick line reads like "SPF 2x4" / "8ft stick" / ea.
    stick_lines = [ln for ln in po.lines if ln.spec.endswith("stick")]
    assert stick_lines
    ln = stick_lines[0]
    assert ln.unit == "ea" and ln.item.startswith("SPF")


def test_total_includes_stick_cost():
    est = estimate(BenchSpec(species="spf", leg=38, leg_depth=89))
    assert est.total == pytest.approx(
        est.material_cost + est.lumber_cost + est.stick_cost
        + est.hardware_cost + est.edge_banding_cost + est.labour_cost
        + est.finish_cost)


# --- validator advisories --------------------------------------------------

def test_near_dimensional_advisory_fires():
    # A 91mm square leg is ~2mm off a 4x4 (89) — advise snapping onto stock.
    issues = validate(TableSpec(leg=91)).issues
    msgs = [i.message for i in issues if i.severity == "info"]
    assert any("4x4" in m and "no ripping" in m for m in msgs)


def test_exact_dimensional_section_is_silent():
    # A leg already exactly a 4x4 (89) gets no near-miss advisory.
    issues = validate(TableSpec(leg=89)).issues
    assert not any("nearly" in i.message for i in issues)


def test_leg_depth_must_be_positive_when_set():
    res = validate(TableSpec(leg=60, leg_depth=-5))
    assert not res.ok
    assert any(i.field == "leg_depth" for i in res.issues)


def test_construction_species_suppresses_milling_hint():
    from woodworking_ai.materials import build_hints

    spf = [m for _, _, m in build_hints(_ff_cab(species="spf"))]
    assert not any("15% extra" in m for m in spf)
    assert any("S4S" in m and "no milling" in m for m in spf)
    walnut = [m for _, _, m in build_hints(_ff_cab(species="walnut"))]
    assert any("15% extra" in m for m in walnut)


def _ff_cab(**kw):
    from woodworking_ai import CabinetSpec, Construction
    return CabinetSpec(width=600, height=720, depth=560, doors=2, shelves=1,
                       construction=Construction.FACE_FRAME, material_form="solid",
                       **kw)


def test_dimensional_length_actuals_are_sane():
    # Every catalogue section is smaller than its nominal inches (S4S loss).
    for name, (t, w) in stock.DIMENSIONAL_LUMBER.items():
        nom_t, nom_w = (int(x) for x in name.split("x"))
        assert t < nom_t * 25.4 and w < nom_w * 25.4
        assert math.isfinite(t) and math.isfinite(w)
