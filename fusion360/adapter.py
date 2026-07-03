"""Adapter: a Woodworking AI ``PanelBox`` layout -> native Fusion 360 bodies.

The Phase-1/2 replacement for :mod:`woodworking_ai.builder` (which targets
build123d / OpenCascade). It consumes the *same* ``geometry.panel_layout()``
output -- the single source of truth the Critic measures against -- and emits
native Fusion ``BRepBody`` solids, so **no build123d / OpenCascade is needed
inside Fusion's embedded Python**.

Each panel is built in its **own centred local frame** (axis X=width, Y=depth,
Z=height through the panel centre), exactly like ``builder.py``: the box, then
its through ``openings``, then -- when ``machined`` -- the dados/rabbets/grooves
and bores from the project's own joinery + drilling schedules, then the whole
solid is rotated about Z and translated into the shared frame. Cutting in the
local frame means this mirrors ``builder.py``'s geometry one-to-one, so the
Fusion bodies and the exported STEP can never disagree with the shop paperwork.

Coordinate frames
-----------------
``woodworking_ai`` is millimetre-native; the Fusion API works in **centimetres**
with the same axis meaning, so the only conversion is ``mm / 10 -> cm``
(:data:`MM_TO_CM`).
"""

import math

import adsk.core
import adsk.fusion

MM_TO_CM = 0.1


def _pt(x, y, z):
    return adsk.core.Point3D.create(x, y, z)


def _vec(x, y, z):
    return adsk.core.Vector3D.create(x, y, z)


def _diff():
    return adsk.fusion.BooleanTypes.DifferenceBooleanType


# ---------------------------------------------------------------------------
# Local-frame primitives (all sizes already in cm).
# ---------------------------------------------------------------------------
def _local_box(brep_mgr, center, dims):
    """An axis-aligned box of full extents ``dims`` centred on ``center`` (cm)."""
    obb = adsk.core.OrientedBoundingBox3D.create(
        _pt(*center), _vec(1.0, 0.0, 0.0), _vec(0.0, 1.0, 0.0), *dims
    )
    return brep_mgr.createBox(obb)


# ---------------------------------------------------------------------------
# Machine-honest cutting -- mirrors builder._apply_joinery / _apply_bores, in
# the panel's centred local frame. Sizes are converted mm -> cm up front.
# ---------------------------------------------------------------------------
def _normal_axis(size):
    """Index (0=X, 1=Y, 2=Z) of the panel's thickness axis (smallest size).

    Ties prefer Z last so a thin flat panel keeps its broad face in X/Y.
    """
    sx, sy, sz = size
    if sx <= sy and sx <= sz:
        return 0
    if sy <= sx and sy <= sz:
        return 1
    return 2


def _plane_axis(size, normal):
    """The in-plane horizontal axis (the one that is neither normal nor Z)."""
    return next(i for i in (0, 1, 2) if i != normal and i != 2)


def _apply_joinery(brep_mgr, solid, ops, size_cm, inner_sign=1.0):
    """Subtract a dado/rabbet/groove box per housed joinery op (cm frame).

    ``inner_sign`` (+1/-1) says which thickness face is the assembly interior, so
    a mirrored right-hand panel gets its housing on the inner face, not outside.
    """
    from woodworking_ai.joinery import classify_joinery_edge, JoineryEdge

    sx, sy, sz = size_cm
    half = {0: sx / 2, 1: sy / 2, 2: sz / 2}
    normal = _normal_axis(size_cm)
    plane = _plane_axis(size_cm, normal)
    span = {0: sx, 1: sy, 2: sz}[plane]
    for op in ops:
        width = float(getattr(op, "width", 0.0) or 0.0) * MM_TO_CM
        depth = float(getattr(op, "depth", 0.0) or 0.0) * MM_TO_CM
        if width <= 0.0 or depth <= 0.0:
            continue                       # not a housed (box-shaped) cut
        edge = classify_joinery_edge(str(getattr(op, "reference", "")))
        dims = [0.0, 0.0, 0.0]
        pos = [0.0, 0.0, 0.0]
        if edge is JoineryEdge.REAR:
            # Vertical housing near the rear edge, full height, into the face.
            dims[plane] = width
            dims[2] = sz * 2.0
            dims[normal] = depth * 2.0
            pos[plane] = half[plane] - width / 2.0   # park at the back edge
            pos[normal] = inner_sign * half[normal]  # break the inner face
        else:
            # Horizontal dado across the panel for a bottom/top shelf.
            dims[plane] = span * 1.01
            dims[2] = width
            dims[normal] = depth * 2.0
            if edge is JoineryEdge.TOP:
                pos[2] = half[2] - width / 2.0
            else:                                    # bottom (default housed)
                pos[2] = -half[2] + width / 2.0
            pos[normal] = inner_sign * half[normal]
        cutter = _local_box(brep_mgr, pos, dims)
        brep_mgr.booleanOperation(solid, cutter, _diff())
    return solid


def _apply_bores(brep_mgr, solid, holes, size_cm, inner_sign=1.0):
    """Subtract a cylinder per hole (through when as deep as the stock; cm).

    ``inner_sign`` picks which thickness face a blind bore sinks in from, so a
    right-hand panel's shelf-pin/runner holes are bored from its inner face."""
    sx, sy, sz = size_cm
    half = {0: sx / 2, 1: sy / 2, 2: sz / 2}
    normal = _normal_axis(size_cm)
    plane = _plane_axis(size_cm, normal)
    thickness = {0: sx, 1: sy, 2: sz}[normal]
    for h in holes:
        dia = float(getattr(h, "dia", 0.0) or 0.0) * MM_TO_CM
        depth = float(getattr(h, "depth", 0.0) or 0.0) * MM_TO_CM
        if dia <= 0.0 or depth <= 0.0:
            continue
        through = depth >= thickness - 1e-6
        cut_len = (thickness + 0.2) if through else depth   # +2 mm overshoot
        pos = [0.0, 0.0, 0.0]
        pos[plane] = -half[plane] + float(getattr(h, "u", 0.0)) * MM_TO_CM
        pos[2] = -half[2] + float(getattr(h, "v", 0.0)) * MM_TO_CM
        if through:
            pos[normal] = 0.0
        else:
            # Sink from the inner face (±normal per ``inner_sign``) inward.
            pos[normal] = inner_sign * (half[normal] - depth / 2.0 + 0.1)
        p1 = list(pos)
        p2 = list(pos)
        p1[normal] -= cut_len / 2.0
        p2[normal] += cut_len / 2.0
        cyl = brep_mgr.createCylinderOrCone(_pt(*p1), dia / 2.0, _pt(*p2),
                                            dia / 2.0)
        brep_mgr.booleanOperation(solid, cyl, _diff())
    return solid


# ---------------------------------------------------------------------------
# Panel -> placed body.
# ---------------------------------------------------------------------------
def panel_to_brep(brep_mgr, panel, machining=None):
    """Build one placed panel as a temporary ``BRepBody``.

    ``machining`` is an optional ``(joinery_ops, holes)`` pair; when given the
    cuts are attempted on a copy and silently dropped on any failure, so a single
    bad boolean degrades to the plain (opening-cut) slab rather than crashing.
    """
    sx, sy, sz = (v * MM_TO_CM for v in panel.size)
    size_cm = (sx, sy, sz)

    solid = _local_box(brep_mgr, (0.0, 0.0, 0.0), size_cm)

    # Through cut-outs (sink / cooktop): offset is in the panel's local X/Y.
    for opening in getattr(panel, "openings", ()) or ():
        ox, oy, ow, od = opening
        cutter = _local_box(
            brep_mgr, (ox * MM_TO_CM, oy * MM_TO_CM, 0.0),
            (ow * MM_TO_CM, od * MM_TO_CM, sz * 2.0),
        )
        brep_mgr.booleanOperation(solid, cutter, _diff())

    if machining:
        ops, holes = machining
        if ops or holes:
            try:
                sign = float(getattr(panel, "inner_sign", 1.0) or 1.0)
                work = brep_mgr.copy(solid)
                if ops:
                    _apply_joinery(brep_mgr, work, ops, size_cm, sign)
                if holes:
                    _apply_bores(brep_mgr, work, holes, size_cm, sign)
                solid = work
            except Exception:
                pass   # degrade to the plain slab on any cutting failure

    # Place into the shared frame: rotate about Z through the panel centre, then
    # translate to the centre.
    matrix = adsk.core.Matrix3D.create()
    matrix.setToRotation(
        math.radians(getattr(panel, "rot_z", 0.0)), _vec(0.0, 0.0, 1.0),
        _pt(0.0, 0.0, 0.0),
    )
    matrix.translation = _vec(*(v * MM_TO_CM for v in panel.center))
    brep_mgr.transform(solid, matrix)
    return solid


def _body_name(panel):
    sub = getattr(panel, "subassembly", "") or ""
    return f"{sub} · {panel.label}" if sub else panel.label


# ---------------------------------------------------------------------------
# Machining lookup (the same schedules the cut list and setup sheets use).
# ---------------------------------------------------------------------------
def _machining_tables(spec):
    """``({part_id: {"joinery": [...], "holes": [...]}}, cutlist)`` or ``({}, None)``.

    Degrade-safe: any schedule failure disables machining rather than the build.
    """
    try:
        from woodworking_ai.joinery import joinery_schedule
        from woodworking_ai.drilling import drilling_schedule, holes_by_part_id
        from woodworking_ai.cutlist import generate_cutlist

        cuts = {}
        for op in joinery_schedule(spec).ops:
            if op.part_id:
                cuts.setdefault(op.part_id, {}).setdefault("joinery", []).append(op)
        for pid, ops in holes_by_part_id(drilling_schedule(spec)).items():
            holes = cuts.setdefault(pid, {}).setdefault("holes", [])
            for op in ops:
                holes.extend(op.holes)
        return cuts, generate_cutlist(spec)
    except Exception:
        return {}, None


def _resolve_machining(panel, cuts, cutlist):
    """The ``(joinery_ops, holes)`` for *panel*, or ``None`` if it has none."""
    if not cuts or cutlist is None:
        return None
    try:
        pid = cutlist.part_id_for_label(panel.label)
    except Exception:
        pid = ""
    bucket = cuts.get(pid) if pid else None
    if not bucket:
        return None
    return (bucket.get("joinery") or [], bucket.get("holes") or [])


def _build_panels(component, panels, cuts, cutlist):
    """Add *panels* into *component* as named bodies, one ``BaseFeature`` entry."""
    brep_mgr = adsk.fusion.TemporaryBRepManager.get()
    base = component.features.baseFeatures.add()
    base.startEdit()
    bodies = []
    try:
        for panel in panels:
            machining = _resolve_machining(panel, cuts, cutlist)
            temp = panel_to_brep(brep_mgr, panel, machining)
            body = component.bRepBodies.add(temp, base)
            body.name = _body_name(panel)
            bodies.append(body)
    finally:
        base.finishEdit()
    return bodies


def build_into_component(spec, component, *, machined=True):
    """Compile *spec* into *component*: one named ``BRepBody`` per panel."""
    from woodworking_ai.geometry import panel_layout

    cuts, cutlist = _machining_tables(spec) if machined else ({}, None)
    return _build_panels(component, panel_layout(spec), cuts, cutlist)


# ---------------------------------------------------------------------------
# Spec dimensions as Fusion user parameters (reference documentation).
# ---------------------------------------------------------------------------
def _spec_parameters(spec):
    """``[(name, value_mm, comment)]`` for the spec's primary scalar dimensions."""
    params = []
    for attr, label in (("width", "overall width"),
                        ("height", "overall height"),
                        ("depth", "overall depth")):
        value = getattr(spec, attr, None)
        if isinstance(value, (int, float)) and value > 0:
            params.append((f"woodai_{attr}", float(value), label))
    material = getattr(spec, "material", None)
    for attr, label in (("carcass", "carcass sheet thickness"),
                        ("back", "back panel thickness"),
                        ("door", "door thickness")):
        value = getattr(material, attr, None)
        if isinstance(value, (int, float)) and value > 0:
            params.append((f"woodai_{attr}_thickness", float(value), label))
    return params


def write_user_parameters(design, spec):
    """Write the spec's dimensions as Fusion user parameters (reference only).

    They document the design inside Fusion; the DSL spec remains the source of
    truth, so editing a value and re-importing -- not dragging the parameter --
    re-drives the geometry. Existing parameters are updated, not duplicated.
    """
    user_params = design.userParameters
    written = []
    for name, value_mm, comment in _spec_parameters(spec):
        existing = user_params.itemByName(name)
        value = adsk.core.ValueInput.createByString(f"{value_mm} mm")
        if existing:
            existing.expression = f"{value_mm} mm"
        else:
            user_params.add(name, value, "mm",
                            f"{comment} (reference — edit the spec & re-import)")
        written.append(name)
    return written


# ---------------------------------------------------------------------------
# Top-level import.
# ---------------------------------------------------------------------------
def import_spec(spec, design, *, machined=True, by_subassembly=True):
    """Place *spec* as a new component in *design* and build its geometry.

    With ``by_subassembly`` each buildable unit (Carcass, Doors, Drawer box,
    Countertop…) becomes its own child component for a real assembly tree;
    otherwise every panel lands in one component. With ``machined`` the panel
    solids carry their dados/rabbets/grooves and bores. Returns
    ``(component, bodies)``.
    """
    from woodworking_ai.geometry import panel_layout

    root = design.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    parent = occ.component
    parent.name = getattr(spec, "name", None) or "Woodworking AI"

    panels = panel_layout(spec)
    cuts, cutlist = _machining_tables(spec) if machined else ({}, None)

    bodies = []
    if by_subassembly:
        groups = {}
        for panel in panels:
            groups.setdefault(panel.unit, []).append(panel)
        for unit, unit_panels in groups.items():
            sub_occ = parent.occurrences.addNewComponent(
                adsk.core.Matrix3D.create()
            )
            sub_occ.component.name = unit
            bodies += _build_panels(sub_occ.component, unit_panels, cuts, cutlist)
    else:
        bodies = _build_panels(parent, panels, cuts, cutlist)

    try:
        write_user_parameters(design, spec)
    except Exception:
        pass   # parameters are documentation; never block the build

    return parent, bodies
