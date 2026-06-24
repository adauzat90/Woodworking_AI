"""Display-unit formatting: render mm dimensions as metric or imperial.

The engine is **millimetre-native end to end** — all geometry, validation, and
engineering math stay in mm. This module is a thin *display* layer that converts
mm to inches for output (cut lists, reports, the web UI) without ever changing
the internal representation.

US shops work in **fractional inches**, so the imperial formatter snaps a length
to a fraction (default 1/16in, the way a tape measure reads) and reduces it,
producing e.g. ``23-7/8"`` rather than the unhelpful ``23.8125"``.

Pure functions over plain numbers — no spec types, no CAD — so it is trivially
unit-testable and reusable by ``cutlist``, ``estimator``, ``critic`` and the CLI.
"""

from __future__ import annotations

import math
from math import gcd

MM_PER_IN = 25.4
MM_PER_FT = 304.8
SQ_M_PER_SQ_FT = 0.09290304

METRIC = "metric"
IMPERIAL = "imperial"

# Accepted spellings for the imperial display unit (case-insensitive).
_IMPERIAL_ALIASES = {"in", "inch", "inches", "imperial", "us", "ft", "feet"}


def normalize_unit(unit: str | None) -> str:
    """Map any user/spec unit string to ``METRIC`` or ``IMPERIAL``."""
    return IMPERIAL if str(unit or "").strip().lower() in _IMPERIAL_ALIASES else METRIC


def length_unit_label(unit: str | None) -> str:
    """Short column/axis label for the chosen unit: ``"in"`` or ``"mm"``."""
    return "in" if normalize_unit(unit) == IMPERIAL else "mm"


def mm_to_in(mm: float) -> float:
    return mm / MM_PER_IN


def format_inches(mm: float, denom: int = 16, *, mark: bool = True) -> str:
    """Render *mm* as fractional inches snapped to the nearest ``1/denom``.

    ``mark`` appends the inch mark (``"``); turn it off for CSV cells. Whole
    inches drop the fraction (``24"``); sub-inch lengths drop the whole part
    (``7/8"``); the fraction is reduced to lowest terms.
    """
    if not math.isfinite(mm):
        return "—"
    sign = "-" if mm < 0 else ""
    units = round(abs(mm) / MM_PER_IN * denom)        # count of 1/denom inches
    whole, frac = divmod(units, denom)
    suffix = '"' if mark else ""
    if frac == 0:
        return f"{sign}{whole}{suffix}"
    g = gcd(frac, denom)
    frac, den = frac // g, denom // g
    if whole == 0:
        return f"{sign}{frac}/{den}{suffix}"
    return f"{sign}{whole}-{frac}/{den}{suffix}"


def format_length(mm: float, unit: str | None = METRIC, *, mark: bool = True,
                  mm_decimals: int = 1) -> str:
    """Format a mm length in the chosen display unit.

    Metric keeps the engine's millimetre value; imperial snaps to 1/16in.
    """
    if normalize_unit(unit) == IMPERIAL:
        return format_inches(mm, mark=mark)
    if not math.isfinite(mm):
        return "—"
    s = f"{mm:.{mm_decimals}f}"
    return f"{s} mm" if mark else s


def format_area(area_m2: float, unit: str | None = METRIC, *, mark: bool = True) -> str:
    """Format a sheet-goods area: square metres or square feet."""
    if normalize_unit(unit) == IMPERIAL:
        ft2 = area_m2 / SQ_M_PER_SQ_FT
        return f"{ft2:.1f} ft²" if mark else f"{ft2:.1f}"
    return f"{area_m2:.2f} m²" if mark else f"{area_m2:.2f}"


def format_run_mm(mm: float, unit: str | None = METRIC, *, mark: bool = True) -> str:
    """Format a linear run given in mm (e.g. edge banding): metres or feet."""
    if normalize_unit(unit) == IMPERIAL:
        ft = mm / MM_PER_FT
        return f"{ft:.1f} ft" if mark else f"{ft:.1f}"
    m = mm / 1000.0
    return f"{m:.1f} m" if mark else f"{m:.1f}"
