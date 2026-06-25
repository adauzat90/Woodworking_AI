"""Kitchen accessories: countertops, appliance cutouts, fillers, end panels,
crown / light-rail / scribe moldings.

A real cabinet or run lives or dies on the parts *around* the box — the
countertop and its sink/cooktop cutout, the filler that closes a gap to the
wall, the finished end panel on an exposed side, and the moldings. These are
modelled as a light list of accessory dicts on a :class:`CabinetSpec`
(``accessories``), each ``{"kind": ...}``:

    {"kind": "countertop", "depth": 640, "thickness": 38,
     "material": "butcher_block", "overhang": 25}
    {"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450}
    {"kind": "filler", "width": 75, "side": "left"}
    {"kind": "end_panel", "side": "left"}
    {"kind": "molding", "type": "crown", "profile": "cove", "height": 90}

They add parts to the cut list and quote, and are sanity-checked by the
validator (e.g. a sink cutout must fit the cabinet). Pure data — no CAD.
"""

from __future__ import annotations


def _num(d: dict, key: str, default: float) -> float:
    v = d.get(key, default)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _bool(d: dict, key: str, default: bool = False) -> bool:
    return bool(d.get(key, default))


def _counter_dims(a: dict, spec) -> tuple[float, float]:
    """The countertop blank's ``(length, width)`` for accessory dict *a*.

    Mirrors the part the cut list emits: length runs the cabinet width, width is
    the counter depth plus its front overhang.
    """
    depth = _num(a, "depth", spec.depth + 25.0)
    overhang = _num(a, "overhang", 25.0)
    return spec.width, depth + overhang


def countertop_cutouts(spec) -> list[tuple[float, float, float, float]]:
    """Sink/cooktop cut-outs to remove from the countertop, in its own frame.

    Each opening is ``(x, y, w, d)`` — the front-left corner plus size — within
    the countertop blank (``length`` along the cabinet width, ``width`` along the
    counter depth). A sink/cooktop appliance's ``cutout_w``/``cutout_d`` size the
    hole; it is centred over the host unless the accessory carries an explicit
    ``cutout_x``/``cutout_y`` (front-left corner, same frame). Returns ``[]``
    when there is no countertop or no sink/cooktop appliance to host.
    """
    accs = [a for a in getattr(spec, "accessories", None) or []
            if isinstance(a, dict)]
    counter = next(
        (a for a in accs if str(a.get("kind", "")).lower() == "countertop"), None)
    if counter is None:
        return []
    length, width = _counter_dims(counter, spec)
    out: list[tuple[float, float, float, float]] = []
    for a in accs:
        if str(a.get("kind", "")).lower() != "appliance":
            continue
        if str(a.get("type", "")).lower() not in ("sink", "cooktop"):
            continue
        cw = _num(a, "cutout_w", 0.0)
        cd = _num(a, "cutout_d", 0.0)
        if cw <= 0 or cd <= 0:
            continue
        x = _num(a, "cutout_x", (length - cw) / 2.0)
        y = _num(a, "cutout_y", (width - cd) / 2.0)
        out.append((x, y, cw, cd))
    return out


def add_accessory_parts(cl, spec) -> None:
    """Append cut-list parts for every accessory on *spec* (in place)."""
    from .cutlist import Part   # local import avoids a cycle

    for a in getattr(spec, "accessories", None) or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind", "")).lower()
        if kind == "countertop":
            depth = _num(a, "depth", spec.depth + 25.0)
            thick = _num(a, "thickness", 38.0)
            overhang = _num(a, "overhang", 25.0)
            mat = str(a.get("material", "laminate"))
            cutouts = countertop_cutouts(spec)
            note = f"{mat}, {overhang:.0f}mm overhang"
            if cutouts:
                # CNC/joinery op: each opening is cut out of the slab; the
                # quoted/finishable area drops by it (see Part.area_m2).
                sizes = "; ".join(f"{w:.0f}×{d:.0f}mm" for (_x, _y, w, d) in cutouts)
                note += f" — sink/cooktop cutout ({sizes})"
            cl.parts.append(Part(
                "Countertop", 1, length=spec.width, width=depth + overhang,
                thickness=thick, material="countertop", grain="length",
                notes=note, openings=cutouts))
        elif kind == "filler":
            w = _num(a, "width", 75.0)
            side = str(a.get("side", ""))
            cl.parts.append(Part(
                "Filler", 1, length=spec.box_height, width=w,
                thickness=spec.material.carcass, material="frame", grain="length",
                notes=f"scribe to wall{f' ({side})' if side else ''}"))
        elif kind == "end_panel":
            side = str(a.get("side", ""))
            cl.parts.append(Part(
                "End panel", 1, length=spec.box_height, width=spec.depth,
                thickness=spec.material.door, material="door/front", grain="length",
                notes=f"finished exposed side{f' ({side})' if side else ''}"))
        elif kind == "molding":
            mtype = str(a.get("type", "crown"))
            height = _num(a, "height", 90.0 if mtype == "crown" else 40.0)
            cl.parts.append(Part(
                f"{mtype.replace('_', ' ').title()} molding", 1,
                length=spec.width, width=height, thickness=spec.material.carcass,
                material="molding", grain="length",
                notes=str(a.get("profile", "")) or mtype))
        # "appliance" adds no part — it's the cutout, checked by the validator.


def accessory_issues(spec) -> list:
    """Return (severity, field, message) tuples for accessory sanity checks."""
    out = []
    interior = spec.interior_width
    has_counter = any(
        isinstance(a, dict) and str(a.get("kind", "")).lower() == "countertop"
        for a in getattr(spec, "accessories", None) or [])
    has_panel = any(
        isinstance(a, dict)
        and str(a.get("kind", "")).lower() in ("end_panel", "door_panel")
        for a in getattr(spec, "accessories", None) or [])
    for a in getattr(spec, "accessories", None) or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind", "")).lower()
        if kind == "appliance":
            cw = _num(a, "cutout_w", 0.0)
            cd = _num(a, "cutout_d", 0.0)
            atype = str(a.get("type", "appliance")).lower()
            if cw and cw > interior:
                out.append((
                    "error", "appliance",
                    f"{atype} cutout {cw:.0f}mm is wider than the {interior:.0f}mm "
                    "interior; it won't fit the cabinet"))
            elif cw and cw > interior - 20:
                out.append((
                    "warning", "appliance",
                    f"{atype} cutout leaves under 10mm each side; tight fit"))
            if cd and cd > spec.depth - 40:
                out.append((
                    "warning", "appliance",
                    f"{atype} cutout {cd:.0f}mm deep leaves little counter at "
                    "front/back"))
            # --- per-type rules (additive) -------------------------------
            if atype in ("sink", "cooktop") and not has_counter:
                out.append((
                    "warning", "appliance",
                    f"a {atype} cutout needs a countertop accessory to host it; "
                    "add a \"countertop\" accessory"))
            if _bool(a, "panel_ready") and not has_panel:
                out.append((
                    "warning", "appliance",
                    f"panel-ready {atype} needs a finish panel; add an "
                    "\"end_panel\" or door panel accessory"))
            if atype in ("range", "dishwasher", "fridge"):
                out.append((
                    "info", "appliance",
                    f"a {atype} occupies a GAP in the run, not a cabinet; leave "
                    "an opening rather than building a box for it"))
        elif kind == "filler":
            if _num(a, "width", 75.0) <= 0:
                out.append(("error", "filler", "filler width must be positive"))
        elif kind == "countertop":
            if _num(a, "overhang", 25.0) > 100:
                out.append((
                    "warning", "countertop",
                    "counter overhang over 100mm needs support brackets"))

    # --- kind / enum-value sanity (additive; advisory) -------------------
    from .dsl import ACCESSORY_SIDES, MOLDING_TYPES
    known_kinds = {"countertop", "appliance", "filler", "end_panel",
                   "door_panel", "molding"}
    for a in getattr(spec, "accessories", None) or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind", "")).strip().lower()
        if kind and kind not in known_kinds:
            out.append((
                "warning", "accessory",
                f"unknown accessory kind {kind!r}; expected one of "
                f"{', '.join(sorted(known_kinds))}"))
        if kind in ("filler", "end_panel"):
            side = str(a.get("side", "")).strip().lower()
            if side and side not in ACCESSORY_SIDES:
                out.append((
                    "warning", kind,
                    f"side {side!r} should be one of {', '.join(ACCESSORY_SIDES)}"))
        if kind == "molding":
            mtype = str(a.get("type", "crown")).strip().lower()
            if mtype and mtype not in MOLDING_TYPES:
                out.append((
                    "warning", "molding",
                    f"molding type {mtype!r} not recognized; expected one of "
                    f"{', '.join(MOLDING_TYPES)}"))
    return out


# --- appliance voids in a run -----------------------------------------------

def void_end_panels(project) -> dict[int, list[str]]:
    """Cabinet sides left exposed by an adjacent appliance gap, per component.

    A free-standing appliance in a run (a :class:`~dsl.ApplianceVoid`) leaves the
    sides of the cabinets on either side of it on show, so they want a finished
    end panel. Returns ``{component_index: [side, ...]}`` (1-based, "left"/
    "right" in the cabinet's own frame) for the cabinets that abut a void; a run
    with no void returns ``{}``.

    Adjacency is decided from each component's plan footprint, so it works for a
    straight run laid left-to-right (the common kitchen case). The side facing
    the gap is the one whose edge touches the void.
    """
    from .dsl import ApplianceVoid
    from .geometry import footprint_corners

    comps = list(getattr(project, "components", []) or [])
    if not comps:
        return {}

    def x_span(comp):
        xs = [p[0] for p in footprint_corners(comp)]
        return min(xs), max(xs)

    spans = [x_span(c) for c in comps]
    out: dict[int, list[str]] = {}
    tol = 5.0
    for vi, comp in enumerate(comps):
        if not isinstance(comp.spec, ApplianceVoid):
            continue
        vlo, vhi = spans[vi]
        for ci, other in enumerate(comps):
            if ci == vi or isinstance(other.spec, ApplianceVoid):
                continue
            olo, ohi = spans[ci]
            if abs(ohi - vlo) <= tol:        # cabinet sits to the LEFT of the gap
                out.setdefault(ci + 1, []).append("right")
            elif abs(olo - vhi) <= tol:      # cabinet sits to the RIGHT of the gap
                out.setdefault(ci + 1, []).append("left")
    return {k: sorted(set(v)) for k, v in out.items()}
