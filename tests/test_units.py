"""Tests for the metric/imperial display-formatting layer."""

import math

from woodworking_ai import units
from woodworking_ai.cutlist import generate_cutlist
from woodworking_ai import CabinetSpec, Material


def test_normalize_unit_aliases():
    for s in ("in", "Inch", "inches", "imperial", "US", "ft"):
        assert units.normalize_unit(s) == units.IMPERIAL
    for s in ("mm", "metric", "", None, "cm", "garbage"):
        assert units.normalize_unit(s) == units.METRIC


def test_format_inches_whole_and_fraction():
    assert units.format_inches(25.4) == '1"'          # exactly 1 in
    assert units.format_inches(304.8) == '12"'        # 12 in
    # 600 mm = 23.622 in -> nearest 1/16 is 23-5/8"
    assert units.format_inches(600.0) == '23-5/8"'
    # sub-inch reduces and drops the whole part
    assert units.format_inches(25.4 * 0.5) == '1/2"'
    assert units.format_inches(0.0) == '0"'


def test_format_inches_rounds_to_sixteenth_and_reduces():
    # 18 mm = 0.7087 in -> nearest 1/16 = 11/16 (0.6875) vs 12/16 (0.75);
    # 0.7087*16 = 11.34 -> rounds to 11 -> 11/16"
    assert units.format_inches(18.0) == '11/16"'
    # a value landing on 8/16 must reduce to 1/2
    assert units.format_inches(25.4 * 1.5) == '1-1/2"'


def test_format_inches_mark_toggle_and_nonfinite():
    assert units.format_inches(600.0, mark=False) == "23-5/8"
    assert units.format_inches(math.nan) == "—"
    assert units.format_inches(math.inf) == "—"


def test_format_length_dispatch():
    assert units.format_length(600.0, "metric") == "600.0 mm"
    assert units.format_length(600.0, "metric", mark=False) == "600.0"
    assert units.format_length(600.0, "imperial") == '23-5/8"'


def test_format_area_and_run():
    assert units.format_area(1.0, "metric") == "1.00 m²"
    # 1 m² = 10.7639 ft²
    assert units.format_area(1.0, "imperial") == "10.8 ft²"
    assert units.format_run_mm(1000.0, "metric") == "1.0 m"
    # 1000 mm = 3.28 ft
    assert units.format_run_mm(1000.0, "imperial") == "3.3 ft"


def _spec():
    return CabinetSpec(width=600, height=720, depth=560,
                       material=Material(carcass=18))


def test_cutlist_csv_metric_header_unchanged():
    csv = generate_cutlist(_spec()).to_csv()           # default metric
    assert csv.splitlines()[0] == (
        "id,part,qty,length_mm,width_mm,thickness_mm,material,grain,notes")


def test_cutlist_csv_imperial_header_and_values():
    csv = generate_cutlist(_spec()).to_csv("imperial")
    head, *rows = csv.splitlines()
    assert head == (
        "id,part,qty,length_in,width_in,thickness_in,material,grain,notes")
    # The dimensional columns (length/width/thickness) carry no mm values;
    # notes/metric hardware (e.g. 5mm pins) may legitimately stay metric.
    for r in rows:
        cols = r.split(",")
        assert "mm" not in "".join(cols[3:6])   # length/width/thickness columns
    assert any(r.split(",")[5] == "11/16" for r in rows)   # 18mm carcass
    # CSV cells stay comma/quote-free so the file parses cleanly.
    assert '"' not in csv


def test_cutlist_summary_units():
    cl = generate_cutlist(_spec())
    assert "m²" in cl.summary("metric")
    assert "ft²" in cl.summary("imperial")


# --- G6b: imperial-first default for the CLI (WOODAI_UNITS) ----------------

def test_cli_default_unit_from_env(monkeypatch):
    from woodworking_ai.cli import _default_unit
    monkeypatch.delenv("WOODAI_UNITS", raising=False)
    assert _default_unit() == "metric"          # mm-native default
    for v in ("in", "inch", "inches", "imperial", "IN"):
        monkeypatch.setenv("WOODAI_UNITS", v)
        assert _default_unit() == "imperial", v
    for v in ("mm", "metric", "garbage"):
        monkeypatch.setenv("WOODAI_UNITS", v)
        assert _default_unit() == "metric", v
