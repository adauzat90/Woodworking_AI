"""Real-world stock catalog — what a shop can actually buy.

Lets the validator check that a design maps onto real material (the MAT-* rules
in docs/validation-rules.md): standard sheet-good thicknesses and sizes, and the
hardwood quarter system with its surfacing loss. Pure data + helpers, no deps.

All lengths in mm.
"""

from __future__ import annotations

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
    "sheet": ("Carcass sheet", "plywood / MDF / melamine"),
    "back panel": ("Back & drawer-bottom panel", "thin ply or hardboard"),
    "door/front": ("Door & drawer-front panel", "veneer ply / MDF"),
    "door panel": ("Door centre-panel stock", "thin ply or solid"),
    "drawer box": ("Drawer-box sheet", "Baltic birch / solid"),
    "countertop": ("Countertop slab", "laminate / solid surface / butcher block"),
    "molding": ("Molding stock", "solid profile"),
    "frame": ("Face-frame hardwood", "solid stock"),
    "solid panel": ("Solid-wood boards", "for edge-glued panels"),
    "top": ("Tabletop stock", "solid / sheet"),
    "leg": ("Leg stock", "solid hardwood"),
    "apron": ("Apron stock", "solid hardwood"),
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


def required_quarter(finished_thickness: float) -> tuple[str, float] | None:
    """Smallest hardwood quarter whose *surfaced* thickness yields the finished
    dimension. Returns (name, surfaced_mm), or None if beyond 12/4 (must
    laminate). A small 0.5mm grace covers rounding.
    """
    for name, (_rough, surfaced) in HARDWOOD_QUARTERS.items():
        if surfaced + 0.5 >= finished_thickness:
            return name, surfaced
    return None
