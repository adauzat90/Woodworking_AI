"""Finishing schedule + finishable surface area.

Finishing is often a third of the labour and a real line on the quote, but a cut
list says nothing about it. This module derives a finishing schedule from the
spec's ``finish`` choice — the sanding grit sequence, the coats, the finishable
surface area, and the litres of finish — so the quote and the bench checklist
include it. Pure arithmetic — no CAD dependency.
"""

from __future__ import annotations

from .materials import (
    MAT_BACK, MAT_DRAWER_BOX, MAT_DOOR_FRONT, MAT_DOOR_PANEL, MAT_FRAME,
    MAT_TOP, MAT_LEG, MAT_APRON, MAT_COUNTERTOP, MAT_MOLDING,
)

# Optional bridge to the species database (H5). The species DB is the authority
# on which finishing *class* a wood falls in (blotch / oily / open-pore); we own
# the wording and the fact that a wood can fall in more than one class at once
# (walnut is oily *and* open-pore), which the DB's single note can't express. So
# we take the DB's classification and add it to our own, then render our notes.
# Never a hard dependency — absent, only the local lists below classify.
try:  # pragma: no cover - exercised only when species.py exists
    from .species import finishing_category as _sp_category
except Exception:  # species module absent or has no such helper
    _sp_category = None

# (grit sequence, total coats, description). Coats count sealer/primer + topcoats.
FINISHES = {
    "none": ([], 0, "Leave unfinished / pre-finished"),
    "oil": ([120, 180, 220], 2, "Wipe-on oil / hardwax, 2 coats"),
    "clear": ([120, 150, 180], 3, "Sealer + 2 clear topcoats"),
    "paint": ([120, 150, 180], 3, "Primer + 2 colour coats"),
    "stain_clear": ([120, 150, 180, 220], 4, "Stain + sealer + 2 topcoats"),
}
COVERAGE_M2_PER_L = 10.0     # one coat covers ~10 m² per litre

# Drying / recoat window per finish family, in hours. Hobbyists routinely recoat
# too soon and trap solvent or witness-line the film; these are the
# manufacturer-typical windows at ~20°C / normal humidity. (min, max) hours.
RECOAT_WINDOW_H = {
    "none": (0.0, 0.0),
    "oil": (6.0, 8.0),          # wipe-on oil / hardwax-oil
    "clear": (2.0, 2.0),        # waterborne clear
    "paint": (2.0, 4.0),        # waterborne / latex
    "stain_clear": (24.0, 24.0),  # oil-based topcoat over stain
}


def recoat_window(ftype: str) -> tuple[float, float]:
    """`(min, max)` hours to wait before recoating *ftype* (0,0 if no coats)."""
    return RECOAT_WINDOW_H.get(str(ftype).lower(), (0.0, 0.0))


def _recoat_text(ftype: str) -> str:
    lo, hi = recoat_window(ftype)
    if hi <= 0:
        return ""
    span = f"{lo:g}h" if lo == hi else f"{lo:g}-{hi:g}h"
    return (f"Allow ~{span} between coats (recoat window); de-nib with a fine "
            "pad before the next coat.")


# Per-species finishing notes, grouped by the failure mode the species invites.
# Local, additive table — kept here so finishing has no hard dependency on the
# species database (H5). A species can appear in more than one group (e.g.
# walnut is both oily and open-pore), so each matching note is surfaced.
_BLOTCH_PRONE = ("pine", "cherry", "soft maple", "maple", "birch", "alder",
                 "poplar")
_OILY = ("walnut", "teak", "rosewood", "cocobolo", "ipe", "wenge")
_OPEN_PORE = ("oak", "ash", "walnut", "mahogany", "wenge")

_BLOTCH_NOTE = ("blotch-prone — condition before staining (wash-coat / "
                "gel stain) so the colour lands even.")
_OILY_NOTE = ("naturally oily — wipe with solvent (acetone/naphtha) just "
              "before glue-up and before finishing so glue and film bond.")
_OPEN_PORE_NOTE = ("open-pore — grain-fill for a glass-smooth finish (or "
                   "leave the texture if you want an open-grain look).")


# Finishing classes (match species.FINISH_* values) → our note wording.
_CLASS_NOTE = {
    "blotch-prone": _BLOTCH_NOTE, "oily": _OILY_NOTE, "open-pore": _OPEN_PORE_NOTE,
}


def _species_note(species: str) -> str | None:
    """Finishing note(s) for one *species*, or None.

    Classifies the wood from our local lists *and* the H5 species database (a
    wood can be in more than one class — walnut is oily and open-pore), then
    renders our wording in a stable order.
    """
    sp = str(species or "").strip().lower()
    if not sp:
        return None
    classes: set[str] = set()
    if any(sp == w or sp.endswith(" " + w) for w in _BLOTCH_PRONE):
        classes.add("blotch-prone")
    if any(sp == w or sp.endswith(" " + w) for w in _OILY):
        classes.add("oily")
    if any(sp == w or sp.endswith(" " + w) for w in _OPEN_PORE):
        classes.add("open-pore")
    if _sp_category is not None:                    # pragma: no cover
        try:
            cat = _sp_category(sp)
            if cat in _CLASS_NOTE:
                classes.add(cat)
        except Exception:
            pass
    hits = [_CLASS_NOTE[c] for c in ("blotch-prone", "oily", "open-pore")
            if c in classes]
    if not hits:
        return None
    return f"{species.strip().title()}: " + " ".join(hits)


def species_finishing_notes(spec) -> list[str]:
    """Per-species finishing advice for every species declared on *spec*.

    Resolves species the same way the BOM does (global ``species`` + per-area
    ``stock`` overrides, via :func:`materials.declared_materials`), so the notes
    match the wood actually being bought. Falls back to scanning resolved part
    species when nothing is declared globally. Deterministic, de-duplicated.
    """
    species: set[str] = set()
    try:
        from .materials import declared_materials
        _forms, declared = declared_materials(spec)
        species |= {s for s in declared}
    except Exception:
        pass
    # Also pick up species stamped on resolved parts (e.g. shelf_species), so a
    # cabinet with a species only on one area still gets its note.
    try:
        from .cutlist import generate_cutlist
        for p in generate_cutlist(spec).parts:
            if getattr(p, "species", ""):
                species.add(str(p.species).strip().title())
    except Exception:
        pass
    notes: list[str] = []
    seen: set[str] = set()
    for sp in sorted(species):
        note = _species_note(sp)
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return notes

# How many faces of a part see finish, by material.
_HIDDEN = {MAT_BACK, MAT_DRAWER_BOX}
_BOTH_FACES = {MAT_DOOR_FRONT, MAT_DOOR_PANEL, MAT_FRAME, MAT_TOP, MAT_LEG,
               MAT_APRON, MAT_COUNTERTOP, MAT_MOLDING}


def _faces(material: str) -> float:
    if material in _HIDDEN:
        return 0.0
    if material in _BOTH_FACES:
        return 2.0
    return 1.0   # carcass / shelf: the shown interior face


def finish_area_m2(spec) -> float:
    """Total finishable surface area (m²) for *spec* (both faces where shown)."""
    from .cutlist import generate_cutlist
    cl = generate_cutlist(spec)
    return sum(_faces(p.material) * p.area_m2 * p.qty for p in cl.parts)


def finishing_schedule(spec) -> dict:
    """Sanding/finish schedule for *spec*: grits, coats, area, litres, steps."""
    ftype = str(getattr(spec, "finish", "none")).lower()
    grits, coats, desc = FINISHES.get(ftype, FINISHES["none"])
    area = finish_area_m2(spec) if coats else 0.0
    litres = area * coats / COVERAGE_M2_PER_L if coats else 0.0
    species_notes = species_finishing_notes(spec)
    recoat_lo, recoat_hi = recoat_window(ftype) if coats else (0.0, 0.0)
    recoat_note = _recoat_text(ftype) if coats else ""
    steps = [f"Sand to {g} grit" for g in grits]
    if coats:
        for n in species_notes:
            steps.append(n)
        steps.append(desc)
        if recoat_note:
            steps.append(recoat_note)
        steps.append("Final scuff between coats; ease all edges")
    return {
        "type": ftype,
        "sheen": str(getattr(spec, "finish_sheen", "satin")),
        "grits": grits,
        "coats": coats,
        "area_m2": round(area, 2),
        "litres": round(litres, 2),
        "description": desc,
        "steps": steps,
        # H4 additions (additive; all existing keys above are unchanged).
        "species_notes": species_notes,
        "recoat_hours": [recoat_lo, recoat_hi],
        "recoat_note": recoat_note,
    }


def finish_cost(spec, per_m2_per_coat: float) -> tuple[float, float]:
    """Return ``(cost, area_m2)`` for finishing *spec* at the given rate."""
    s = finishing_schedule(spec)
    return (s["area_m2"] * s["coats"] * per_m2_per_coat, s["area_m2"])
