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


def resolve_modulus(species: str | None) -> tuple[float, bool]:
    """``(E in MPa, resolved)`` for a named material.

    Prefers the wood-species database (:mod:`species`) when the name is a known
    wood, so the value tracks the one real table; falls back to the local
    :data:`MODULUS_MPA` map (which also covers sheet goods like plywood/MDF that
    aren't woods), and finally to plywood.

    ``resolved`` is ``False`` only when *species* is a **non-blank name that
    matched neither table**, so the plywood default was substituted silently — the
    caller can then surface a warning instead of validating a real wood as
    plywood. A blank/``None`` species reports ``resolved=True`` (using the default
    is the documented behaviour, not a typo).
    """
    if not species or not str(species).strip():
        return DEFAULT_MODULUS, True
    from . import species as _species
    e = _species.modulus(species)
    if e is not None:
        return e, True
    key = str(species).strip().lower()
    if key in MODULUS_MPA:
        return MODULUS_MPA[key], True
    return DEFAULT_MODULUS, False


def modulus_for(species: str | None) -> float:
    """Young's modulus (MPa) for a named material, defaulting to plywood.

    Thin wrapper over :func:`resolve_modulus` for callers that only want E.
    """
    return resolve_modulus(species)[0]


@dataclass
class ShelfResult:
    """Outcome of a shelf deflection check. All lengths in mm."""
    deflection: float      # predicted mid-span sag (mm)
    span: float            # unsupported span (mm)
    engineering_limit: float  # span/360 (mm)
    visible_limit: float      # visible-sag threshold (mm)
    modulus: float = DEFAULT_MODULUS  # E (MPa) used for the calculation
    species_resolved: bool = True     # False -> species name unknown, plywood used

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
    modulus, resolved = resolve_modulus(species)
    # kg/m -> N/mm:  (kg/m · g) gives N/m; /1000 gives N/mm.
    load_per_length = max(load_kg_per_m, 0.0) * GRAVITY / 1000.0
    deflection = shelf_deflection(span, depth, thickness, load_per_length, modulus)
    return ShelfResult(
        deflection=deflection,
        span=span,
        engineering_limit=span * DEFLECTION_ENGINEERING,
        visible_limit=span * DEFLECTION_VISIBLE,
        modulus=modulus,
        species_resolved=resolved,
    )


def seasonal_movement(width: float, grain: str = "flatsawn",
                      species: str | None = None) -> float:
    """Estimated seasonal cross-grain movement of a solid panel (mm).

    `width` is the dimension measured *across* the grain. Quartersawn stock moves
    roughly half as much as flatsawn.

    When *species* names a known wood, its species-specific movement fraction is
    used (walnut/cherry are stable, beech/hard maple move a lot); otherwise the
    global flatsawn/quartersawn constants apply, exactly as before.
    """
    if species:
        from . import species as _species
        if _species.known(species):
            return max(width, 0.0) * _species.movement_fraction(species, grain)
    coeff = MOVEMENT_QUARTERSAWN if str(grain).lower().startswith("quarter") \
        else MOVEMENT_FLATSAWN
    return max(width, 0.0) * coeff


# Stiffness (Young's modulus E, MPa) of engineered beam products that aren't a
# named wood species. Built-up / solid sawn beams use softwood framing lumber;
# LVL and glulam are stiffer manufactured members. Customary US figures
# (1e6 psi = 6894.76 MPa).
ENGINEERED_MODULUS_MPA: dict[str, float] = {
    "built_up": MODULUS_MPA["softwood"],     # plies of SPF/SYP dimensional lumber
    "solid_timber": MODULUS_MPA["softwood"],  # a solid sawn timber
    "glulam": 12400.0,                       # ~1.8e6 psi
    "lvl": 13800.0,                          # ~2.0e6 psi
}


def beam_modulus(material: str | None, species: str | None = None) -> float:
    """Young's modulus (MPa) for a beam of *material*, or its *species* if named.

    A declared wood species wins (resolved through the species table, exactly like
    a shelf); otherwise the engineered-product table maps built_up / solid_timber
    / lvl / glulam to a stiffness, defaulting to softwood framing lumber.
    """
    if species and str(species).strip():
        return resolve_modulus(species)[0]
    key = str(material or "").strip().lower()
    return ENGINEERED_MODULUS_MPA.get(key, MODULUS_MPA["softwood"])


def max_beam_span(
    width: float,
    depth: float,
    modulus: float,
    load_per_length: float,
    deflection_ratio: float = 1.0 / DEFLECTION_ENGINEERING,
) -> float:
    """Greatest clear span (mm) a rectangular beam carries within a sag limit.

    Inverts the simply-supported, uniformly loaded deflection δ = 5·w·L⁴/(384·E·I)
    at the acceptance limit δ = L / ``deflection_ratio`` (e.g. L/240), giving a
    closed form  L = (384·E·I / (5·w·R))**(1/3)  with section I = b·h³/12.
    ``load_per_length`` is the line load on the beam in N/mm (its tributary area
    load times the spacing). Returns 0 for a degenerate section/load.
    """
    if width <= 0 or depth <= 0 or modulus <= 0 or load_per_length <= 0 \
            or deflection_ratio <= 0:
        return 0.0
    moment_of_inertia = width * depth ** 3 / 12.0
    return (384.0 * modulus * moment_of_inertia
            / (5.0 * load_per_length * deflection_ratio)) ** (1.0 / 3.0)


def beam_deflection_ratio(
    span: float,
    width: float,
    depth: float,
    modulus: float,
    load_per_length: float,
) -> float:
    """Span-to-deflection ratio (L/δ) of a loaded beam — bigger is stiffer.

    The inverse view of :func:`max_beam_span`: given an actual clear *span*, how
    stiff is the beam? Returns ``inf`` for no load/deflection. Compare against an
    acceptance ratio (240 typical for a floor/ceiling beam) to judge a layout.
    """
    deflection = shelf_deflection(span, width, depth, load_per_length, modulus)
    if deflection <= 0:
        return float("inf")
    return span / deflection


def tip_safety_factor(height: float, depth: float) -> float:
    """Crude static tip-over proxy: footprint depth relative to height.

    Higher is safer. A shallow, tall case (small depth / large height) tips
    easily. This is a screening heuristic, NOT a substitute for the ASTM F2057
    physical test, which loads and extends a drawer to simulate a climbing child.
    """
    if height <= 0:
        return float("inf")
    return depth / height
