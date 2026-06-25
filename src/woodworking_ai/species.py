"""Wood-species database: the physical data behind the free-text species label.

A single, pure-data table of the woods a home shop actually uses, with the
numbers the rest of the engine wants — bending modulus (drives shelf sag),
Janka hardness, density, a per-species seasonal-movement fraction, and a rough
$/board-foot — plus short workability and finishing notes.

Everything is plain data and pure functions over names: no CAD, no spec types,
no heavy imports, so it is fast and trivially unit-testable. Lookups are
case/space/alias tolerant ("White Oak", "white_oak" and "oak" all resolve), and
every lookup degrades gracefully to ``None`` / a sensible default for an unknown
or blank species.

Units mirror :mod:`engineering`: modulus in MPa (N/mm^2), density in kg/m^3,
Janka in lbf, movement as a dimensionless flatsawn fraction of width, price in
currency-units per board foot.
"""

from __future__ import annotations

from dataclasses import dataclass

# Finishing-note categories (free text in the record, but these constants keep
# the advisory wiring in materials/validator from typo-drifting).
FINISH_EASY = "easy"
FINISH_BLOTCH = "blotch-prone"
FINISH_OILY = "oily"
FINISH_OPEN_PORE = "open-pore"


@dataclass(frozen=True)
class Species:
    """Physical + practical data for one wood. All fields are typical values;
    real boards vary, so these are screening figures, not guarantees."""
    name: str               # canonical, display-friendly name
    janka: float            # hardness, lbf
    modulus_mpa: float      # Young's bending modulus E, MPa (N/mm^2)
    density_kg_m3: float    # air-dry density, kg/m^3
    movement_flatsawn: float  # seasonal cross-grain movement fraction, flatsawn
    workability: str        # short shop note
    finishing: str          # short finishing note
    price_per_bdft: float | None  # rough $/board-foot, None if unpriced

    @property
    def movement_quartersawn(self) -> float:
        """Quartersawn stock moves roughly half as much as flatsawn."""
        return self.movement_flatsawn / 2.0


# Typical flatsawn seasonal movement fractions are derived from published
# tangential shrinkage over a normal indoor humidity swing (~6–8% MC change).
# They sit around the engine's global 0.0208 flatsawn constant, but differ by
# species: walnut and cherry are stable, beech/hickory/hard-maple move a lot.
_TABLE: list[Species] = [
    Species("pine", 420, 8300.0, 420, 0.018,
            "soft, easy to cut but dents and can tear out; sappy knots gum blades",
            "blotch-prone — use conditioner before stain", 4.0),
    Species("poplar", 540, 10900.0, 450, 0.020,
            "very easy to machine; soft, paints beautifully but green streaks",
            "blotch-prone if stained; usually painted — prime first", 4.5),
    Species("alder", 590, 9500.0, 450, 0.017,
            "soft, machines cleanly; the classic paint-grade and stain-grade wood",
            "blotch-prone — condition before stain (takes 'cherry' tones well)", 5.0),
    Species("soft_maple", 950, 10000.0, 540, 0.022,
            "machines well, a touch softer than hard maple; good value",
            "blotch-prone — use conditioner before stain", 6.0),
    Species("hard_maple", 1450, 12600.0, 705, 0.026,
            "dense and stiff but burns and dulls blades; the stiffest shelf wood",
            "blotch-prone — use conditioner before stain", 8.0),
    Species("birch", 1260, 13000.0, 670, 0.024,
            "hard, stiff, machines cleanly; plywood-grade face wood",
            "blotch-prone — condition before stain", 6.0),
    Species("beech", 1300, 11800.0, 720, 0.027,
            "hard and stiff but moves a lot; steam-bends well",
            "fairly easy; condition before dark stain", 7.0),
    Species("red_oak", 1290, 12400.0, 700, 0.021,
            "machines well; coarse open grain shows tool marks less",
            "open-pore — grain-fill for a glass finish", 8.5),
    Species("white_oak", 1360, 12400.0, 755, 0.021,
            "tough, machines well; closed pores make it weather/water resistant",
            "open-pore — grain-fill for a glass finish", 11.0),
    Species("ash", 1320, 12000.0, 670, 0.022,
            "stiff and tough, machines well; springy, steam-bends",
            "open-pore — grain-fill for a glass finish", 8.0),
    Species("hickory", 1820, 14900.0, 800, 0.026,
            "very hard and tough — hard on blades, prone to tear-out",
            "open-pore — grain-fill for a glass finish", 9.0),
    Species("cherry", 950, 10300.0, 560, 0.013,
            "machines beautifully; very stable, darkens with light over time",
            "blotch-prone — use conditioner before stain", 12.0),
    Species("walnut", 1010, 11600.0, 610, 0.012,
            "machines beautifully; stable, the premium dark furniture wood",
            "oily — wipe with solvent before glue/finish", 18.0),
    Species("mahogany", 800, 9700.0, 540, 0.012,
            "machines easily and stays put; classic, very stable",
            "open-pore — grain-fill for a glass finish (oily, wipe first)", 14.0),
    # Generic fallback: middle-of-the-road hardwood numbers for an unknown wood.
    Species("generic", 1000, 11000.0, 600, 0.020,
            "treat as a generic hardwood; verify against the real stock",
            "test a finish on an offcut first", None),
]

GENERIC = _TABLE[-1]

# Name -> Species, plus aliases. Canonical names use underscores; common short
# names ("oak", "maple") and spaced/hyphenated forms all resolve.
_BY_NAME: dict[str, Species] = {s.name: s for s in _TABLE}

# Aliases map a loose name onto a canonical one. Bare "oak"/"maple" pick the
# common builder default (red oak, hard maple).
_ALIASES: dict[str, str] = {
    "oak": "red_oak",
    "maple": "hard_maple",
    "rock_maple": "hard_maple",
    "sugar_maple": "hard_maple",
    "softmaple": "soft_maple",
    "hardmaple": "hard_maple",
    "redoak": "red_oak",
    "whiteoak": "white_oak",
    "fir": "pine",
    "douglas_fir": "pine",
    "spruce": "pine",
    "softwood": "pine",
    "black_walnut": "walnut",
    "american_walnut": "walnut",
    "honduran_mahogany": "mahogany",
    "sapele": "mahogany",
}


def normalize(name: object) -> str:
    """Canonical key for a loose species name (lower, trimmed, spaces->_)."""
    key = str(name or "").strip().lower().replace("-", "_")
    key = "_".join(key.split())   # collapse internal whitespace to underscores
    return _ALIASES.get(key, key)


def get(name: object) -> Species | None:
    """The :class:`Species` record for *name*, or ``None`` if unknown/blank.

    Use :data:`GENERIC` explicitly when a fallback record is wanted instead.
    """
    if not str(name or "").strip():
        return None
    return _BY_NAME.get(normalize(name))


def known(name: object) -> bool:
    """True when *name* resolves to a real species in the table."""
    return get(name) is not None


def names() -> list[str]:
    """Canonical species names (excluding the generic fallback), sorted."""
    return sorted(s.name for s in _TABLE if s.name != "generic")


def modulus(name: object) -> float | None:
    """Bending modulus E (MPa) for *name*, or ``None`` if unknown."""
    s = get(name)
    return s.modulus_mpa if s is not None else None


def janka(name: object) -> float | None:
    """Janka hardness (lbf) for *name*, or ``None`` if unknown."""
    s = get(name)
    return s.janka if s is not None else None


def density(name: object) -> float | None:
    """Air-dry density (kg/m^3) for *name*, or ``None`` if unknown."""
    s = get(name)
    return s.density_kg_m3 if s is not None else None


def movement_fraction(name: object, grain: object = "flatsawn") -> float:
    """Seasonal cross-grain movement fraction for *name* and *grain*.

    Quartersawn returns roughly half the flatsawn value. Falls back to the
    :data:`GENERIC` record's fraction for an unknown/blank species, so callers
    always get a usable number.
    """
    s = get(name) or GENERIC
    quarter = str(grain).strip().lower().startswith("quarter")
    return s.movement_quartersawn if quarter else s.movement_flatsawn


def finishing_note(name: object) -> str:
    """Short finishing note for *name*, or the generic 'test first' note."""
    s = get(name) or GENERIC
    return s.finishing


def workability_note(name: object) -> str:
    """Short workability note for *name*, or the generic note."""
    s = get(name) or GENERIC
    return s.workability


def price_per_bdft(name: object) -> float | None:
    """Rough $/board-foot for *name*, or ``None`` if unknown/unpriced."""
    s = get(name)
    return s.price_per_bdft if s is not None else None


# --- finishing-advisory classification -------------------------------------
# Used by materials/validator to surface a species-aware finishing tip. Keyed
# off the canonical finishing note so the categories stay in one place.

def finishing_category(name: object) -> str | None:
    """The finishing class of *name* — one of the FINISH_* constants — or None
    for an unknown species or a species with no special handling."""
    s = get(name)
    if s is None:
        return None
    note = s.finishing.lower()
    if "blotch" in note:
        return FINISH_BLOTCH
    if "oily" in note:
        return FINISH_OILY
    if "open-pore" in note or "open pore" in note:
        return FINISH_OPEN_PORE
    return FINISH_EASY
