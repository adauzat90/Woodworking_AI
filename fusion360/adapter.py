"""Adapter: a Woodworking AI ``PanelBox`` layout -> native Fusion 360 bodies.

This is the Phase-1 replacement for :mod:`woodworking_ai.builder` (which targets
build123d / OpenCascade). It consumes the *same* ``geometry.panel_layout()``
output -- the single source of truth the Critic measures against -- and emits
native Fusion ``BRepBody`` solids, so **no build123d / OpenCascade is needed
inside Fusion's embedded Python**.

Coordinate frames
-----------------
``woodworking_ai`` is millimetre-native::

    X = width   (left -> right, 0 at the centre)
    Y = depth   (front -> back, 0 at the carcass front face)
    Z = height  (floor -> up,   0 at the floor)

The Fusion API works in **centimetres** with the same axis meaning, so the only
conversion is ``mm / 10 -> cm`` (:data:`MM_TO_CM`). A panel's ``rot_z`` (used by
the diagonal-corner door) is a rotation about the vertical Z axis through the
panel centre -- it maps onto the box's length/width direction vectors.

Each ``PanelBox`` becomes one box solid; any through ``openings`` (a countertop
sink / cooktop cut-out) are boolean-subtracted, mirroring ``builder.py``.
"""

import math

import adsk.core
import adsk.fusion

MM_TO_CM = 0.1


def _pt(x, y, z):
    return adsk.core.Point3D.create(x, y, z)


def _vec(x, y, z):
    return adsk.core.Vector3D.create(x, y, z)


def _box_brep(brep_mgr, center_cm, dirs, size_cm):
    """A temporary box solid: full extents ``size_cm`` about ``center_cm``."""
    length_dir, width_dir = dirs
    sx, sy, sz = size_cm
    obb = adsk.core.OrientedBoundingBox3D.create(
        _pt(*center_cm), length_dir, width_dir, sx, sy, sz
    )
    return brep_mgr.createBox(obb)


def panel_to_brep(brep_mgr, panel):
    """Build one panel (with its through cut-outs) as a temporary ``BRepBody``."""
    cx, cy, cz = (v * MM_TO_CM for v in panel.center)
    sx, sy, sz = (v * MM_TO_CM for v in panel.size)

    angle = math.radians(getattr(panel, "rot_z", 0.0))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    length_dir = _vec(cos_a, sin_a, 0.0)
    width_dir = _vec(-sin_a, cos_a, 0.0)
    dirs = (length_dir, width_dir)

    body = _box_brep(brep_mgr, (cx, cy, cz), dirs, (sx, sy, sz))

    # Through cut-outs (sink / cooktop). Each opening is ``(ox, oy, ow, od)`` in
    # the panel's *local* X/Y (mm), centred on the panel; rotate the offset into
    # world and cut a box that runs past both faces in Z.
    for opening in getattr(panel, "openings", ()) or ():
        ox, oy, ow, od = opening
        ox_cm, oy_cm = ox * MM_TO_CM, oy * MM_TO_CM
        wx = cx + ox_cm * cos_a - oy_cm * sin_a
        wy = cy + ox_cm * sin_a + oy_cm * cos_a
        cutter = _box_brep(
            brep_mgr, (wx, wy, cz), dirs, (ow * MM_TO_CM, od * MM_TO_CM, sz * 2.0)
        )
        brep_mgr.booleanOperation(
            body, cutter, adsk.fusion.BooleanTypes.DifferenceBooleanType
        )
    return body


def _body_name(panel):
    sub = getattr(panel, "subassembly", "") or ""
    return f"{sub} · {panel.label}" if sub else panel.label


def build_into_component(spec, component):
    """Compile *spec* into *component*: one named ``BRepBody`` per panel.

    All bodies are added inside a single ``BaseFeature`` so the import is one
    timeline entry (and works in a parametric design). Returns the list of
    created bodies.
    """
    from woodworking_ai.geometry import panel_layout

    panels = panel_layout(spec)
    brep_mgr = adsk.fusion.TemporaryBRepManager.get()

    base = component.features.baseFeatures.add()
    base.startEdit()
    bodies = []
    try:
        for panel in panels:
            temp = panel_to_brep(brep_mgr, panel)
            body = component.bRepBodies.add(temp, base)
            body.name = _body_name(panel)
            bodies.append(body)
    finally:
        base.finishEdit()
    return bodies


def import_spec(spec, design):
    """Place *spec* as a new child component in *design* and build its geometry.

    A fresh component (so repeated imports don't collide) named after the spec.
    Returns ``(component, bodies)``.
    """
    root = design.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    component = occ.component
    component.name = getattr(spec, "name", None) or "Woodworking AI"
    bodies = build_into_component(spec, component)
    return component, bodies
