"""Real-world stock catalog — what a shop can actually buy.

Lets the validator check that a design maps onto real material (the MAT-* rules
in docs/validation-rules.md): standard sheet-good thicknesses and sizes, and the
hardwood quarter system with its surfacing loss. Pure data + helpers, no deps.

All lengths in mm.
"""

from __future__ import annotations

import math

from .materials import (
    MAT_SHEET, MAT_BACK, MAT_DOOR_FRONT, MAT_DOOR_PANEL, MAT_DRAWER_BOX,
    MAT_COUNTERTOP, MAT_MOLDING, MAT_FRAME, MAT_SOLID_PANEL, MAT_TOP, MAT_LEG,
    MAT_APRON,
)

# Sheet-good thicknesses commonly stocked (metric). Imperial plywood maps to
# these actual thicknesses (e.g. nominal 3/4" ≈ 18mm, 1/2" ≈ 12mm).
SHEET_THICKNESSES_MM = (6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 25.0)

# Imperial nominal -> actual plywood thickness (mm). Sanding removes up to
# ~1/32", so nominal 3/4" arrives at ~23/32" (18.3mm) — cut joinery to actual.
PLYWOOD_NOMINAL_ACTUAL_MM: dict[str, float] = {
    "1/8": 3.2, "1/4": 6.0, "3/8": 9.1, "1/2": 11.9,
    "5/8": 15.1, "3/4": 18.3, "1-1/8": 28.6, "1-1/4": 31.8,
}

# Standard full sheet (8ft x 4ft) and a common oversize panel (10ft x 5ft), mm.
STANDARD_SHEET = (2440.0, 1220.0)
OVERSIZE_SHEET = (3050.0, 1525.0)

# Hardwood quarter system: nominal name -> (rough thickness, surfaced S2S), mm.
# Surfacing loses ~3/16" (4.8mm) per face, so 4/4 (1") finishes near 13/16".
HARDWOOD_QUARTERS: dict[str, tuple[float, float]] = {
    "4/4": (25.4, 20.6),
    "5/4": (31.75, 27.0),
    "6/4": (38.1, 33.3),
    "8/4": (50.8, 46.0),
    "10/4": (63.5, 58.7),
    "12/4": (76.2, 71.4),
}

THICKNESS_TOL = 1.0  # mm tolerance when matching a spec thickness to stock


# The cut list groups parts by an internal *usage* label ("door/front", "drawer
# box", ...). For a shopping list those read like part names, so map each to the
# raw stock a shop actually buys plus the typical product. (name, typical_product)
STOCK_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    MAT_SHEET: ("Carcass sheet", "plywood / MDF / melamine"),
    MAT_BACK: ("Back & drawer-bottom panel", "thin ply or hardboard"),
    MAT_DOOR_FRONT: ("Door & drawer-front panel", "veneer ply / MDF"),
    MAT_DOOR_PANEL: ("Door centre-panel stock", "thin ply or solid"),
    MAT_DRAWER_BOX: ("Drawer-box sheet", "Baltic birch / solid"),
    MAT_COUNTERTOP: ("Countertop slab", "laminate / solid surface / butcher block"),
    MAT_MOLDING: ("Molding stock", "solid profile"),
    MAT_FRAME: ("Face-frame hardwood", "solid stock"),
    MAT_SOLID_PANEL: ("Solid-wood boards", "for edge-glued panels"),
    MAT_TOP: ("Tabletop stock", "solid / sheet"),
    MAT_LEG: ("Leg stock", "solid hardwood"),
    MAT_APRON: ("Apron stock", "solid hardwood"),
}


def stock_label(material: str) -> str:
    """Buyer-friendly name for an internal cut-list material label."""
    return STOCK_DESCRIPTIONS.get(material, (material.title(), ""))[0]


def stock_product(material: str) -> str:
    """The typical product you'd buy for an internal material label (or '')."""
    return STOCK_DESCRIPTIONS.get(material, ("", ""))[1]


def nearest_sheet_thickness(t: float) -> float:
    """Closest commonly stocked sheet thickness (mm)."""
    return min(SHEET_THICKNESSES_MM, key=lambda s: abs(s - t))


def is_standard_sheet_thickness(t: float, tol: float = THICKNESS_TOL) -> bool:
    """True if `t` is (within tolerance) a stocked sheet thickness."""
    return abs(nearest_sheet_thickness(t) - t) <= tol


def fits_standard_sheet(length: float, width: float,
                        sheet: tuple[float, float] = STANDARD_SHEET) -> bool:
    """True if a panel fits on one sheet in either orientation."""
    long_side, short_side = max(length, width), min(length, width)
    return long_side <= sheet[0] + 1e-6 and short_side <= sheet[1] + 1e-6


def actual_sheet_thickness(nominal: float, tol: float = THICKNESS_TOL) -> float:
    """The thickness a nominal sheet *actually* machines to (mm).

    Sheet goods are sold nominal (¾" / 18mm) but arrive thinner after sanding —
    nominal 3/4" is ~18.3mm, an 18mm metric panel is 18.0mm. Joinery cut "to the
    mating thickness" must use this actual value to seat snug. When *nominal*
    already matches an imperial nominal entry within tolerance, the mapped actual
    is returned; otherwise the value is taken as already-actual and returned as
    given (an 18.0mm metric panel is its own actual thickness).
    """
    for actual in PLYWOOD_NOMINAL_ACTUAL_MM.values():
        if abs(actual - nominal) <= tol:
            return actual
    return float(nominal)


def required_quarter(finished_thickness: float) -> tuple[str, float] | None:
    """Smallest hardwood quarter whose *surfaced* thickness yields the finished
    dimension. Returns (name, surfaced_mm), or None if beyond 12/4 (must
    laminate). A small 0.5mm grace covers rounding.
    """
    for name, (_rough, surfaced) in HARDWOOD_QUARTERS.items():
        if surfaced + 0.5 >= finished_thickness:
            return name, surfaced
    return None


# --- construction / dimensional lumber -------------------------------------
# North-American softwood dimensional lumber, sold S4S (surfaced four sides) at
# fixed nominal names whose *actual* section is smaller than the nominal inches
# (a "2x4" is really 1-1/2 x 3-1/2 in = 38 x 89 mm). Unlike the hardwood quarter
# system there is no surfacing/milling loss to plan for — you buy the finished
# section off the shelf and cut to length. nominal name -> (thickness, width) mm.
DIMENSIONAL_LUMBER: dict[str, tuple[float, float]] = {
    "1x2": (19.0, 38.0), "1x3": (19.0, 64.0), "1x4": (19.0, 89.0),
    "1x6": (19.0, 140.0), "1x8": (19.0, 184.0), "1x10": (19.0, 235.0),
    "1x12": (19.0, 286.0),
    "2x2": (38.0, 38.0), "2x3": (38.0, 64.0), "2x4": (38.0, 89.0),
    "2x6": (38.0, 140.0), "2x8": (38.0, 184.0), "2x10": (38.0, 235.0),
    "2x12": (38.0, 286.0),
    "4x4": (89.0, 89.0), "6x6": (140.0, 140.0),
}

# Standard purchasable stick lengths (mm): the 92-5/8in pre-cut wall stud, then
# 8 / 10 / 12 / 16 ft. A shop buys one of these and crosscuts parts from it.
DIMENSIONAL_LENGTHS_MM: tuple[float, ...] = (
    2353.0, 2438.0, 3048.0, 3658.0, 4877.0)

# Buyer-facing label for each standard stick length above.
DIMENSIONAL_LENGTH_LABELS: dict[float, str] = {
    2353.0: "92-5/8in stud", 2438.0: "8ft", 3048.0: "10ft",
    3658.0: "12ft", 4877.0: "16ft",
}

# How close a part's section must be (mm) to count as an exact dimensional match;
# a whisker of tolerance covers rounding between the metric actuals and a spec.
DIMENSIONAL_TOL = 1.5


def dimensional_match(thickness: float, width: float,
                      tol: float = DIMENSIONAL_TOL) -> str | None:
    """Nominal name (e.g. ``"2x4"``) when a cross-section matches a dimensional
    section within *tol*, else ``None``.

    Orientation-agnostic: an 89x38 part is the same 2x4 as a 38x89 one, so both
    axis orders are tried against each catalogue section. When several sections
    are within tolerance the closest (smallest worst-axis error) wins, so a near-
    square section can't be mis-called.
    """
    best: tuple[float, str] | None = None
    for name, (t, w) in DIMENSIONAL_LUMBER.items():
        for a, b in ((thickness, width), (width, thickness)):
            dt, dw = abs(a - t), abs(b - w)
            if dt <= tol and dw <= tol:
                score = max(dt, dw)
                if best is None or score < best[0]:
                    best = (score, name)
    return best[1] if best else None


def nearest_dimensional(thickness: float, width: float) -> str:
    """The dimensional name whose section is closest to (thickness, width).

    For an advisory suggestion ("this is nearly a 2x4"); orientation-agnostic and
    never ``None`` (the catalogue is non-empty). Distance is the Euclidean gap
    between the two sections in the better of the two axis orientations.
    """
    def dist(sec: tuple[float, float]) -> float:
        t, w = sec
        return min(math.hypot(thickness - t, width - w),
                   math.hypot(width - t, thickness - w))
    return min(DIMENSIONAL_LUMBER, key=lambda n: dist(DIMENSIONAL_LUMBER[n]))
