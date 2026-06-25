"""Finishing schedule + finishable surface area.

Finishing is often a third of the labour and a real line on the quote, but a cut
list says nothing about it. This module derives a finishing schedule from the
spec's ``finish`` choice — the sanding grit sequence, the coats, the finishable
surface area, and the litres of finish — so the quote and the bench checklist
include it. Pure arithmetic — no CAD dependency.
"""

from __future__ import annotations

# (grit sequence, total coats, description). Coats count sealer/primer + topcoats.
FINISHES = {
    "none": ([], 0, "Leave unfinished / pre-finished"),
    "oil": ([120, 180, 220], 2, "Wipe-on oil / hardwax, 2 coats"),
    "clear": ([120, 150, 180], 3, "Sealer + 2 clear topcoats"),
    "paint": ([120, 150, 180], 3, "Primer + 2 colour coats"),
    "stain_clear": ([120, 150, 180, 220], 4, "Stain + sealer + 2 topcoats"),
}
COVERAGE_M2_PER_L = 10.0     # one coat covers ~10 m² per litre

# How many faces of a part see finish, by material.
_HIDDEN = {"back panel", "drawer box"}
_BOTH_FACES = {"door/front", "door panel", "frame", "top", "leg", "apron",
               "countertop", "molding"}


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
    steps = [f"Sand to {g} grit" for g in grits]
    if coats:
        steps.append(desc)
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
    }


def finish_cost(spec, per_m2_per_coat: float) -> tuple[float, float]:
    """Return ``(cost, area_m2)`` for finishing *spec* at the given rate."""
    s = finishing_schedule(spec)
    return (s["area_m2"] * s["coats"] * per_m2_per_coat, s["area_m2"])
