"""Physical material resolution: form (plywood / mdf / … / solid) + species.

The DSL lets a design *optionally* declare what each area of a piece is actually
made of — a global default (``material_form`` / ``species`` on the spec) plus
per-area overrides (``stock``). These helpers turn any area into its resolved
``(form, species)``, render that as a buyer-friendly stock name for the shopping
list, and surface material-specific build hints.

Everything is optional and degrades gracefully: with nothing declared, a piece
is treated as a single generic sheet good, exactly as before. Pure data — no
CAD, no heavy imports — so it is fast and trivially unit-testable.
"""

from __future__ import annotations

# Sheet goods are bought by the sheet; "solid" is lumber bought by the board
# foot. Mirrors dsl.MATERIAL_FORMS (kept here too to avoid an import cycle).
SHEET_FORMS = ("plywood", "mdf", "particleboard", "melamine", "hardboard")
SOLID_FORMS = ("solid",)
MATERIAL_FORMS = SHEET_FORMS + SOLID_FORMS

# How each form reads in a shopping list (e.g. "Oak plywood", "Oak solid lumber").
FORM_LABELS = {
    "plywood": "plywood", "mdf": "MDF", "particleboard": "particleboard",
    "melamine": "melamine", "hardboard": "hardboard", "solid": "solid lumber",
}

# Areas whose stock is intrinsically solid lumber: a global *sheet* default must
# not turn a face frame (or a table leg) into plywood.
INTRINSIC_SOLID_AREAS = frozenset({"frame", "solid"})

# Loose area names → the canonical override keys a design may set under `stock`.
AREA_ALIASES = {
    "door": "front", "doors": "front", "fronts": "front", "front": "front",
    "drawer_front": "front",
    "box": "drawer_box", "drawer": "drawer_box", "drawer_box": "drawer_box",
    "carcass": "carcass", "case": "carcass", "box_carcass": "carcass",
    "back": "back", "shelf": "shelf", "shelves": "shelf",
    "frame": "frame", "face_frame": "frame",
    "panel": "door_panel", "door_panel": "door_panel",
    "solid": "solid", "top": "solid", "leg": "solid", "apron": "solid",
    "accessory": "accessory",
}


def _attr(ov, name: str) -> str:
    """Read ``form``/``species`` off a Stock, a dict, or None."""
    if ov is None:
        return ""
    if isinstance(ov, dict):
        return str(ov.get(name, "") or "")
    return str(getattr(ov, name, "") or "")


def _spec_globals(spec) -> tuple[str, str]:
    """The spec's global ``(material_form, species)``, normalised.

    Form is lower-cased (it keys the form tables); species keeps its casing for
    display and is title-cased only where a label needs it.
    """
    form = str(getattr(spec, "material_form", "") or "").strip().lower()
    species = str(getattr(spec, "species", "") or "").strip()
    return form, species


def resolve(spec, area: str) -> tuple[str, str]:
    """Resolve ``(form, species)`` for *area* of *spec*.

    Precedence is: a per-area ``stock`` override, then the spec's global
    ``material_form`` / ``species``, then a sensible default (intrinsically solid
    areas fall back to ``"solid"``; everything else to ``""`` = generic sheet).
    """
    area = AREA_ALIASES.get(area, area)
    table = getattr(spec, "stock", None) or {}
    ov = table.get(area)
    if ov is None:                       # a stored key may be a loose alias
        for k, v in table.items():
            if AREA_ALIASES.get(str(k).strip().lower(), k) == area:
                ov = v
                break

    own_form = _attr(ov, "form").strip().lower()
    own_species = _attr(ov, "species").strip()
    g_form, g_species = _spec_globals(spec)

    form = own_form or g_form
    species = own_species or g_species

    if not form:
        form = "solid" if area in INTRINSIC_SOLID_AREAS else ""
    elif area in INTRINSIC_SOLID_AREAS and form in SHEET_FORMS and not own_form:
        # A global sheet default shouldn't make a face frame / leg "plywood".
        form = "solid"
    return form, species


def is_solid_form(form: str) -> bool:
    return str(form or "").strip().lower() in SOLID_FORMS


# What you actually pick up at the yard for a given form (the "typical product"
# column of the shopping list). Used only when a form is declared.
FORM_PRODUCTS = {
    "plywood": "plywood sheet", "mdf": "MDF panel",
    "particleboard": "particleboard panel", "melamine": "melamine panel",
    "hardboard": "hardboard", "solid": "solid boards (S4S)",
}


def product_hint(form: str, fallback: str = "") -> str:
    """Typical product for a declared *form*, else the usage-based *fallback*."""
    return FORM_PRODUCTS.get(str(form or "").strip().lower(), fallback)


def stock_name(form: str, species: str, *, solid: bool = False,
               fallback: str = "") -> str:
    """Buyer-facing stock name for a resolved ``(form, species)``.

    ``solid`` hints how a species-only (no form) part is bought. ``fallback`` is
    returned when neither form nor species is known (e.g. the legacy usage label).
    """
    form = str(form or "").strip().lower()
    sp = str(species or "").strip().title()
    if form:
        return f"{sp} {FORM_LABELS.get(form, form)}".strip()
    if sp:
        return f"{sp} {'solid lumber' if solid else 'sheet'}".strip()
    return fallback


# Material-specific things a builder needs to know — surfaced as advisories on
# the spec and echoed into the build package's preparation notes.
FORM_BUILD_HINTS = {
    "mdf": ("MDF has no grain and weak edges — don't drive screws into the "
            "edge (use confirmats, dowels, or dominoes), pre-drill faces, and "
            "seal/prime before painting; it's heavy and the dust needs good "
            "extraction."),
    "particleboard": ("Particleboard strips out under plain screws — use "
                      "confirmats or threaded inserts, band every exposed edge, "
                      "and keep it dry (it swells permanently if it gets wet)."),
    "melamine": ("Melamine chips on the off-side of a cut — score the line or "
                 "use a triple-chip blade, band raw edges, and assemble with "
                 "confirmats; ordinary PVA won't bond the foil face."),
    "hardboard": ("Hardboard belongs in backs and drawer bottoms — capture it "
                  "in a groove or rabbet; it carries no structural load itself."),
    "solid": ("Solid wood moves across the grain with humidity — let wide "
              "panels float (don't glue them rigidly cross-grain), alternate "
              "grain direction on glue-ups, and leave room for seasonal "
              "movement."),
}


def declared_materials(spec) -> tuple[set[str], set[str]]:
    """``(forms, species)`` a design *explicitly* declares — globals + overrides.

    Intrinsic defaults (a face frame is always solid) are deliberately excluded:
    a hint should only fire when the designer actually chose a material.
    """
    forms: set[str] = set()
    species: set[str] = set()
    g_form, g_species = _spec_globals(spec)
    if g_form:
        forms.add(g_form)
    if g_species:
        species.add(g_species.title())
    for ov in (getattr(spec, "stock", None) or {}).values():
        f = _attr(ov, "form").strip().lower()
        sp = _attr(ov, "species").strip()
        if f:
            forms.add(f)
        if sp:
            species.add(sp.title())
    return forms, species


def build_hints(spec) -> list[tuple[str, str, str]]:
    """``(severity, field, message)`` advisories for the materials *spec* uses.

    One hint per distinct *declared* form, plus a species note. Always advisory
    (``info``) — a material choice never blocks a build.
    """
    forms, species_used = declared_materials(spec)
    out: list[tuple[str, str, str]] = []
    for f in sorted(forms):
        hint = FORM_BUILD_HINTS.get(f)
        if hint:
            out.append(("info", "material", hint))
    if species_used:
        woods = ", ".join(sorted(species_used))
        out.append(("info", "species",
                    f"Buy {woods} stock with consistent colour/figure across the "
                    "piece; order ~15% extra solid lumber for milling and defects."))
    out.extend(species_finishing_hints(species_used))
    return out


def species_finishing_hints(species_used) -> list[tuple[str, str, str]]:
    """Species-aware finishing advisories for the declared woods.

    Additive ``info`` notes that fire only when a species is declared and the
    species database knows a finishing gotcha for it (blotch-prone, oily, or
    open-pore). Identical messages are de-duplicated so several oak parts emit
    one open-pore note, not many.
    """
    from . import species as _species

    # One canonical message per finishing class; woods are listed in the message.
    bins: dict[str, list[str]] = {}
    for sp in species_used:
        cat = _species.finishing_category(sp)
        if cat in (_species.FINISH_BLOTCH, _species.FINISH_OILY,
                   _species.FINISH_OPEN_PORE):
            bins.setdefault(cat, []).append(str(sp).strip().lower())

    out: list[tuple[str, str, str]] = []
    if _species.FINISH_BLOTCH in bins:
        woods = ", ".join(sorted(set(bins[_species.FINISH_BLOTCH])))
        out.append(("info", "species",
                    f"{woods} blotch when stained — apply a wood conditioner (or "
                    "a wash-coat of dewaxed shellac) before stain, or use a gel "
                    "stain/dye, for even colour."))
    if _species.FINISH_OILY in bins:
        woods = ", ".join(sorted(set(bins[_species.FINISH_OILY])))
        out.append(("info", "species",
                    f"{woods} is oily — wipe the glue and finish surfaces with a "
                    "solvent (acetone/naphtha) just before assembly and finishing "
                    "so the glue bonds and the finish cures."))
    if _species.FINISH_OPEN_PORE in bins:
        woods = ", ".join(sorted(set(bins[_species.FINISH_OPEN_PORE])))
        out.append(("info", "species",
                    f"{woods} has open pores — grain-fill before topcoat for a "
                    "glass-smooth surface, or accept (and embrace) the open texture."))
    return out
