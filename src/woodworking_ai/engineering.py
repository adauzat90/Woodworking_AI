"""First-principles structural & material engineering for the validator.

These are the deterministic calculators referenced by the design knowledge base
(`docs/validation-rules.md`): shelf deflection ("Sagulator"), seasonal wood
movement, and a tip-over stability proxy. They are pure functions over plain
numbers — no CAD, no spec types — so they are trivially unit-testable and reused
by `validator.py`.

Everything is SI-on-mm: lengths in mm, forces in N, stress/modulus in MPa
(N/mm^2). The engine's specs are already in mm, so no unit juggling at the call
site.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- material stiffness (Young's modulus E), MPa = N/mm^2 -------------------
# Converted from the customary US figures in docs/design-principles.md
# (1e6 psi = 6894.76 MPa). Values are typical bending moduli; real stock varies.
MODULUS_MPA: dict[str, float] = {
    "particleboard": 2800.0,   # ~0.4e6 psi — sags badly over span
    "mdf": 3600.0,             # ~0.5e6 psi
    "softwood": 8300.0,        # ~1.2e6 psi (pine/fir)
    "pine": 8300.0,
    "plywood": 10300.0,        # ~1.5e6 psi — good budget shelf
    "poplar": 10900.0,
    "cherry": 10300.0,
    "walnut": 11600.0,
    "birch": 13000.0,
    "oak": 12400.0,            # ~1.8e6 psi
    "maple": 12600.0,          # ~1.83e6 psi — stiffest common shelf wood
}
DEFAULT_MODULUS = MODULUS_MPA["plywood"]

# Seasonal movement coefficient: fractional width change across the grain over a
# normal indoor humidity swing. ~1/4" per 12" flatsawn, ~1/8" per 12" quartered
# (docs/design-principles.md §4.1). Dimensionless.
MOVEMENT_FLATSAWN = 0.25 / 12.0      # ≈ 0.0208
MOVEMENT_QUARTERSAWN = 0.125 / 12.0  # ≈ 0.0104

# Deflection acceptance limits, expressed as a fraction of the span.
DEFLECTION_ENGINEERING = 1.0 / 360.0           # span/360 structural limit
# The eye notices ~1/32" per running foot => 0.79375mm per 304.8mm.
DEFLECTION_VISIBLE = (1.0 / 32.0 * 25.4) / 304.8  # ≈ 0.00260 (stricter)

GRAVITY = 9.80665  # m/s^2


def modulus_for(species: str | None) -> float:
    """Young's modulus (MPa) for a named material, defaulting to plywood."""
    if not species:
        return DEFAULT_MODULUS
    return MODULUS_MPA.get(str(species).strip().lower(), DEFAULT_MODULUS)


@dataclass
class ShelfResult:
    """Outcome of a shelf deflection check. All lengths in mm."""
    deflection: float      # predicted mid-span sag (mm)
    span: float            # unsupported span (mm)
    engineering_limit: float  # span/360 (mm)
    visible_limit: float      # visible-sag threshold (mm)

    @property
    def status(self) -> str:
        if self.deflection > self.engineering_limit:
            return "fail"        # exceeds structural limit -> ERROR
        if self.deflection > self.visible_limit:
            return "visible"     # noticeable sag -> WARNING
        return "ok"


def shelf_deflection(
    span: float,
    depth: float,
    thickness: float,
    load_per_length: float,
    modulus: float,
) -> float:
    """Mid-span deflection of a uniformly loaded, simply-supported shelf (mm).

    Classic beam formula  δ = 5·w·L⁴ / (384·E·I),  with a rectangular section
    I = b·h³/12 (b = shelf depth, h = thickness). `load_per_length` is N/mm.
    """
    if span <= 0 or depth <= 0 or thickness <= 0 or modulus <= 0:
        return 0.0
    moment_of_inertia = depth * thickness ** 3 / 12.0
    return 5.0 * load_per_length * span ** 4 / (384.0 * modulus * moment_of_inertia)


def evaluate_shelf(
    span: float,
    depth: float,
    thickness: float,
    load_kg_per_m: float,
    species: str | None = None,
) -> ShelfResult:
    """Evaluate a shelf against the engineering and visible deflection limits.

    `load_kg_per_m` is the distributed load along the shelf length (a fully
    loaded bookshelf is ~20–40 kg/m of books).
    """
    modulus = modulus_for(species)
    # kg/m -> N/mm:  (kg/m · g) gives N/m; /1000 gives N/mm.
    load_per_length = max(load_kg_per_m, 0.0) * GRAVITY / 1000.0
    deflection = shelf_deflection(span, depth, thickness, load_per_length, modulus)
    return ShelfResult(
        deflection=deflection,
        span=span,
        engineering_limit=span * DEFLECTION_ENGINEERING,
        visible_limit=span * DEFLECTION_VISIBLE,
    )


def seasonal_movement(width: float, grain: str = "flatsawn") -> float:
    """Estimated seasonal cross-grain movement of a solid panel (mm).

    `width` is the dimension measured *across* the grain. Quartersawn stock moves
    roughly half as much as flatsawn.
    """
    coeff = MOVEMENT_QUARTERSAWN if str(grain).lower().startswith("quarter") \
        else MOVEMENT_FLATSAWN
    return max(width, 0.0) * coeff


def tip_safety_factor(height: float, depth: float) -> float:
    """Crude static tip-over proxy: footprint depth relative to height.

    Higher is safer. A shallow, tall case (small depth / large height) tips
    easily. This is a screening heuristic, NOT a substitute for the ASTM F2057
    physical test, which loads and extends a drawer to simulate a climbing child.
    """
    if height <= 0:
        return float("inf")
    return depth / height
