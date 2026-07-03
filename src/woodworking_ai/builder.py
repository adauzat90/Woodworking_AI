"""The compiler: a cabinet spec -> build123d B-Rep geometry.

This is where the parametric language becomes real 3D. We place each panel as a
box in a shared coordinate frame:

    X = width  (left  -> right)
    Y = depth  (front -> back)
    Z = height (floor -> up)

build123d (OpenCascade) is an optional, heavy dependency. The import is lazy so
the rest of the package (DSL, validator, cut list) works without it; geometry
functions raise a clear error if it is missing.

``joinery_geometry=True`` makes the B-Rep *machine honest*: dados/rabbets/grooves
and bores are cut into the panel solids so the exported STEP carries them. It is
opt-in and degrade-safe — with the flag off the output is byte-for-byte the plain
slab model, and any OpenCascade failure on a single part falls back to that
part's un-cut slab rather than crashing the export. The cuts come from the very
same :func:`joinery_schedule`/:func:`drilling_schedule` the shop paperwork uses,
so the geometry can never disagree with the setup sheets.
"""

from __future__ import annotations

import logging
from typing import Any

from .dsl import CabinetSpec, ComponentGroup
from .dispatch import is_group
from .geometry import panel_layout, project_layout, explode_panels
from .joinery import classify_joinery_edge, JoineryEdge

log = logging.getLogger(__name__)


def require_build123d() -> Any:
    try:
        import build123d as b3d  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "build123d is required for geometry/export. Install it with:\n"
            "    pip install build123d\n"
            "(The DSL, validator and cut list work without it.)"
        ) from exc
    return b3d


# --- machine-honest cutting -------------------------------------------------
# A panel solid is a ``Box(*size)`` centred on the origin, *then* translated (and
# optionally Z-rotated) into the shared frame. So joinery and bores are cut in
# the panel's own centred local frame, before placement: X/Y/Z there are the
# panel's own width/depth/height. ``v`` (a hole/joint height) always runs up from
# the bottom edge = local +Z; ``u`` runs across the in-plane face dimension; the
# thickness axis (the panel's smallest dimension, its face normal) is the bore /
# housing depth direction.


def _normal_axis(size: tuple[float, float, float]) -> int:
    """Index (0=X, 1=Y, 2=Z) of the panel's thickness axis (smallest size).

    Ties prefer Z last so a thin flat panel keeps its broad face in X/Y.
    """
    sx, sy, sz = size
    if sx <= sy and sx <= sz:
        return 0
    if sy <= sx and sy <= sz:
        return 1
    return 2


def _plane_axis(size: tuple[float, float, float], normal: int) -> int:
    """The in-plane horizontal axis (the one that is neither normal nor Z)."""
    return next(i for i in (0, 1, 2) if i != normal and i != 2)


def _apply_joinery(panel_solid: Any, ops, size: tuple[float, float, float],
                   b3d: Any, inner_sign: float = 1.0) -> Any:
    """Subtract a dado/rabbet/groove box per housed :class:`JoineryOp`.

    Each op carries a ``width`` (cut width), ``depth`` (cut depth) and a textual
    ``reference`` saying where the housing sits. We only cut width-and-depth
    defined housings (dado/rabbet/groove); pocket/screw/dovetail ops carry no box
    and are left to the drilling schedule / shop. The cutter is a thin box across
    the full in-plane span of the panel, sunk ``depth`` into the thickness face,
    positioned from the referenced edge.
    """
    Box, Pos = b3d.Box, b3d.Pos
    sx, sy, sz = size
    half = {0: sx / 2, 1: sy / 2, 2: sz / 2}
    normal = _normal_axis(size)
    plane = _plane_axis(size, normal)
    span = {0: sx, 1: sy, 2: sz}[plane]
    solid = panel_solid
    for op in ops:
        width = float(getattr(op, "width", 0.0) or 0.0)
        depth = float(getattr(op, "depth", 0.0) or 0.0)
        if width <= 0.0 or depth <= 0.0:
            continue                       # not a housed (box-shaped) cut
        ref = str(getattr(op, "reference", "")).lower()
        # Cutter dimensions: width along Z (a horizontal dado) or along the in-
        # plane axis (a vertical groove), full-span the other way, ``depth`` deep
        # into the thickness face. The housing for the bottom/top runs across the
        # panel (along the plane axis) at a given height; the back rabbet/groove
        # runs vertically near the rear edge.
        dims = [0.0, 0.0, 0.0]
        pos = [0.0, 0.0, 0.0]
        edge = classify_joinery_edge(ref)
        if edge is JoineryEdge.REAR:
            # Vertical housing near the rear edge, full height, into the face.
            dims[plane] = width
            dims[2] = sz * 2.0
            dims[normal] = depth * 2.0
            # Park the rear edge: +plane is the back (Y grows to the rear).
            pos[plane] = half[plane] - width / 2.0
            pos[normal] = inner_sign * half[normal]   # break the inner face
        else:
            # Horizontal dado across the panel for the bottom/top shelf. A TOP
            # reference houses near the top edge; BOTTOM and any unlocated
            # housing default to the bottom.
            dims[plane] = span * 1.01
            dims[2] = width
            dims[normal] = depth * 2.0
            if edge is JoineryEdge.TOP:
                pos[2] = half[2] - width / 2.0
            else:                                # bottom (default housed shelf)
                pos[2] = -half[2] + width / 2.0
            pos[normal] = inner_sign * half[normal]   # break the inner face
        cutter = Pos(*pos) * Box(*dims)
        solid = solid - cutter
    return solid


def _apply_bores(panel_solid: Any, holes, size: tuple[float, float, float],
                 b3d: Any, inner_sign: float = 1.0) -> Any:
    """Subtract a cylinder per :class:`Hole` (through when as deep as the stock).

    ``u`` runs across the in-plane face axis, ``v`` up from the bottom (+Z); the
    bore axis is the thickness (face-normal) direction, sunk ``depth`` from the
    inner face. A depth that meets/exceeds the stock thickness bores through.
    """
    Cylinder, Pos, Rot = b3d.Cylinder, b3d.Pos, b3d.Rot
    sx, sy, sz = size
    half = {0: sx / 2, 1: sy / 2, 2: sz / 2}
    normal = _normal_axis(size)
    plane = _plane_axis(size, normal)
    thickness = {0: sx, 1: sy, 2: sz}[normal]
    solid = panel_solid
    for h in holes:
        dia = float(getattr(h, "dia", 0.0) or 0.0)
        depth = float(getattr(h, "depth", 0.0) or 0.0)
        if dia <= 0.0 or depth <= 0.0:
            continue
        through = depth >= thickness - 1e-6
        cut_len = thickness + 2.0 if through else depth
        # A Cylinder is built along +Z; orient its axis along the panel normal.
        cyl = Cylinder(radius=dia / 2.0, height=cut_len)
        if normal == 0:
            cyl = Rot(0, 90, 0) * cyl
        elif normal == 1:
            cyl = Rot(90, 0, 0) * cyl
        pos = [0.0, 0.0, 0.0]
        pos[plane] = -half[plane] + float(h.u)
        pos[2] = -half[2] + float(h.v)
        if through:
            pos[normal] = 0.0
        else:
            # Sink from the inner face (±normal per ``inner_sign``) inward.
            pos[normal] = inner_sign * (half[normal] - depth / 2.0 + 1.0)
        solid = solid - (Pos(*pos) * cyl)
    return solid


def _cuts_by_part_id(spec: Any) -> dict[str, dict[str, list]]:
    """``{part_id: {"joinery": [ops], "holes": [Hole]}}`` from the schedules.

    The single source of truth: the very joinery/drilling schedules the cut list
    and shop paperwork are built from. Keyed by the shared cut-list part ID so a
    placed panel can look up its own machining by resolving its label.
    """
    from .joinery import joinery_schedule
    from .drilling import drilling_schedule, holes_by_part_id

    out: dict[str, dict[str, list]] = {}
    try:
        for op in joinery_schedule(spec).ops:
            if op.part_id:
                out.setdefault(op.part_id, {}).setdefault("joinery", []).append(op)
        for pid, ops in holes_by_part_id(drilling_schedule(spec)).items():
            bucket = out.setdefault(pid, {})
            holes = bucket.setdefault("holes", [])
            for op in ops:
                holes.extend(op.holes)
    except Exception:  # pragma: no cover - schedules must never break a build
        log.warning("joinery/drilling schedule failed; skipping machine cuts",
                    exc_info=True)
        return {}
    return out


def _machined_solid(base: Any, panel: Any, cuts: dict, cl: Any, b3d: Any) -> Any:
    """Return *base* with this panel's joinery + bores cut, or *base* unchanged.

    Degrade-safe: any OpenCascade failure logs and returns the un-cut slab, so an
    export can never crash on a single part's boolean.
    """
    pid = ""
    try:
        pid = cl.part_id_for_label(panel.label)
    except Exception:  # pragma: no cover - label resolution is best-effort
        pid = ""
    bucket = cuts.get(pid) if pid else None
    if not bucket:
        return base
    solid = base
    sign = float(getattr(panel, "inner_sign", 1.0) or 1.0)
    try:
        ops = bucket.get("joinery") or []
        if ops:
            solid = _apply_joinery(solid, ops, panel.size, b3d, sign)
        holes = bucket.get("holes") or []
        if holes:
            solid = _apply_bores(solid, holes, panel.size, b3d, sign)
    except Exception:
        log.warning("machine cut failed for %s; using plain slab", panel.label,
                    exc_info=True)
        return base
    return solid


def _compound_from_panels(panels, label: str, *, spec: Any = None,
                          joinery_geometry: bool = False) -> Any:
    b3d = require_build123d()
    Box, Pos, Compound, Rot = b3d.Box, b3d.Pos, b3d.Compound, b3d.Rot
    # Only pay for the schedule lookup / booleans when the flag is on.
    cuts: dict = {}
    cl: Any = None
    if joinery_geometry and spec is not None:
        cuts = _cuts_by_part_id(spec)
        if cuts:
            try:
                from .cutlist import generate_cutlist
                cl = generate_cutlist(spec)
            except Exception:  # pragma: no cover - costing must not break a build
                log.warning("cut list failed; skipping machine cuts",
                            exc_info=True)
                cuts = {}
    solids: list[Any] = []
    for p in panels:
        solid = Box(*p.size)
        # Sink/cooktop cut-outs: subtract a through box per opening (offsets are
        # relative to the panel centre; over-tall in Z so the cut passes through).
        for (ocx, ocy, ow, od) in getattr(p, "openings", ()) or ():
            _sx, _sy, sz = p.size
            cutter = Pos(ocx, ocy, 0) * Box(ow, od, sz * 2)
            solid = solid - cutter
        # Machine-honest joinery/bores (opt-in, degrade-safe), cut in the panel's
        # centred local frame before it is placed into the shared frame.
        if cuts and cl is not None:
            solid = _machined_solid(solid, p, cuts, cl, b3d)
        if p.is_rotated:
            solid = Rot(0, 0, p.rot_z) * solid
        solid = Pos(*p.center) * solid
        solid.label = p.label
        solids.append(solid)
    model = Compound(children=solids)
    model.label = label
    return model


def build_model(spec: CabinetSpec, *, factor: float = 0.0,
                include: set | None = None,
                joinery_geometry: bool = False) -> Any:
    """Return a build123d ``Compound`` of labelled panels for *spec*.

    Panel placement comes from :func:`woodworking_ai.geometry.panel_layout`, the
    same source the Critic agent measures against. Accepts a
    :class:`ComponentGroup` (Project or sub-assembly) too.

    ``factor`` > 0 returns an *exploded* model (sub-assemblies separated to show
    how it goes together); ``include`` keeps only the named sub-assemblies (for a
    progressive build view). With both defaults this is the assembled model.

    ``joinery_geometry`` (default off) cuts dados/rabbets/grooves and bores into
    the solids from the joinery/drilling schedules — the exported STEP is then
    machine honest. Off, the output is byte-for-byte the plain slab model.
    """
    if is_group(spec):
        return build_project(spec, factor=factor, include=include,
                             joinery_geometry=joinery_geometry)
    panels = (explode_panels(spec, factor, include)
              if (factor or include is not None) else panel_layout(spec))
    return _compound_from_panels(panels, spec.name, spec=spec,
                                 joinery_geometry=joinery_geometry)


def build_project(project: ComponentGroup, *, factor: float = 0.0,
                  include: set | None = None,
                  joinery_geometry: bool = False) -> Any:
    """Assemble a whole group into one build123d ``Compound`` (a run sections by
    cabinet). Supports the same ``factor``/``include`` explode/reveal options and
    the ``joinery_geometry`` machine-honest cutting flag (default off)."""
    panels = (explode_panels(project, factor, include)
              if (factor or include is not None) else project_layout(project))
    return _compound_from_panels(panels, project.name, spec=project,
                                 joinery_geometry=joinery_geometry)


def measure(model: Any) -> dict[str, float]:
    """Return the model's overall bounding-box dimensions (for the critic)."""
    bb = model.bounding_box()
    return {
        "width": bb.size.X,
        "depth": bb.size.Y,
        "height": bb.size.Z,
        "part_count": len(model.children),
    }

# Backwards-compatible private alias (promoted to public API).
_require_build123d = require_build123d
