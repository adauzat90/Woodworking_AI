"""Estimate the mass of parts and whole pieces from the cut list + densities.

The species DB (:mod:`species`) already carries air-dry density for every solid
wood, so a part's weight is free once the cut list has sized it. Sheet goods
(plywood/MDF/particleboard/…) aren't woods, so their densities live here.

Used by the validator's handling/hanging advisories (HW-007 one-person lift,
STRUCT-043 wall-cabinet hanging). Pure functions over a spec via the cut list —
no CAD. Everything is SI: lengths in mm, density in kg/m^3, mass in kg.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import species as _species

# Sheet-goods densities (kg/m^3). Not woods, so not in the species DB; typical
# air-dry values for a 3/4in panel — real stock varies by core and glue.
SHEET_DENSITY_KG_M3: dict[str, float] = {
    "plywood": 600.0,
    "mdf": 750.0,
    "particleboard": 680.0,
    "melamine": 720.0,      # MDF/particle core + melamine faces
    "hardboard": 900.0,
}
# Fallbacks when form/species don't resolve: the generic-hardwood density for
# solid stock, a mid sheet-goods value otherwise.
DEFAULT_SOLID_DENSITY = _species.GENERIC.density_kg_m3   # 600
DEFAULT_SHEET_DENSITY = 650.0


def material_density(form: object, species_name: object) -> float:
    """Density (kg/m^3) for a part given its *form* and *species*.

    A sheet-goods *form* wins (those aren't woods); otherwise the species DB is
    consulted, falling back to the generic-hardwood density.
    """
    form_key = str(form or "").strip().lower()
    if form_key in SHEET_DENSITY_KG_M3:
        return SHEET_DENSITY_KG_M3[form_key]
    d = _species.density(species_name)
    if d is not None:
        return d
    if form_key and form_key != "solid":
        return DEFAULT_SHEET_DENSITY
    return DEFAULT_SOLID_DENSITY


def piece_mass_kg(length_mm: float, width_mm: float, thickness_mm: float,
                  form: object = "", species_name: object = "") -> float:
    """Mass (kg) of a single rectangular piece. Returns 0 for non-positive dims."""
    if min(length_mm, width_mm, thickness_mm) <= 0:
        return 0.0
    volume_m3 = (length_mm * width_mm * thickness_mm) / 1_000_000_000.0
    return volume_m3 * material_density(form, species_name)


@dataclass
class MassEstimate:
    """The weight breakdown of a piece. All masses in kg."""
    total_kg: float                       # summed over every part × qty
    heaviest_part_kg: float               # the single heaviest *one* part
    heaviest_part_name: str
    parts: list[tuple[str, float]] = field(default_factory=list)  # (name, per-unit kg)


def estimate_mass(spec) -> MassEstimate | None:
    """Estimate the assembled mass of *spec* from its cut list.

    Returns ``None`` (never raises) when the cut list can't be built — mass is an
    advisory, so a failure to estimate must read as "unknown", not "weightless".
    """
    try:
        from .cutlist import generate_cutlist
        cl = generate_cutlist(spec)
    except Exception:
        return None
    total = 0.0
    heaviest = 0.0
    heaviest_name = ""
    parts: list[tuple[str, float]] = []
    for p in cl.parts:
        per_unit = piece_mass_kg(p.length, p.width, p.thickness, p.form, p.species)
        total += per_unit * max(p.qty, 0)
        parts.append((p.name, per_unit))
        if per_unit > heaviest:
            heaviest, heaviest_name = per_unit, p.name
    return MassEstimate(total, heaviest, heaviest_name, parts)
