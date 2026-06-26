"""Drilling schedule: where to bore the holes.

Derives a fabrication drilling schedule from the spec — using the same
:func:`panel_layout` as the compiler so positions never drift:

* **Shelf-pin holes** on the side panels following the 32 mm System (two
  vertical rows of 5 mm holes at a 32 mm pitch).
* **Hinge cup bores** (35 mm) on the doors, count scaled to door height.
* **Drawer-slide mounting lines** on the side panels at each drawer's height.

Pure arithmetic — no CAD dependency. Coordinates are per-part and local to that
panel's face: ``u`` runs along the panel's depth/width, ``v`` upward from its
bottom edge (mm).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import ComponentGroup
from .dispatch import spec_kind, VOID, GROUP, WORKBENCH, NIGHTSTAND, DESK
from .geometry import panel_layout, component_tag, trailing_index, PanelRole
from .cutlist import generate_cutlist
from .hardware import hinge_count, select_slide, PLATE_SCREW_INSET
from .constants import (
    SYSTEM_PITCH, HINGE_CUP_DIA, HINGE_CUP_DEPTH, HINGE_CUP_INSET,
    GEOMETRY_EPSILON,
)

# 32 mm System and boring constants (mm). SYSTEM_PITCH and the hinge-cup
# geometry are shared via constants.py.
PIN_DIA = 5.0
PIN_DEPTH = 12.0
ROW_SETBACK = 37.0          # each pin row in from the front / back edge
PIN_END_MARGIN = 64.0       # first/last pin in from the panel ends
HINGE_END_MARGIN = 90.0     # top/bottom hinge in from the door ends
# Depths of the three slide screws along the side panel: a fixed inset from the
# front, mid-depth (None), and an inset from the back (negative => from rear).
SLIDE_SCREW_DEPTHS = (37.0, None, -50.0)


@dataclass
class Hole:
    face: str            # which part / face
    u: float             # along depth (sides) or width (doors)
    v: float             # up from the panel bottom
    dia: float
    depth: float
    note: str = ""


@dataclass
class DrillOp:
    part: str
    operation: str
    holes: list[Hole] = field(default_factory=list)
    note: str = ""
    part_id: str = ""        # shared cut-list part code (e.g. "A1"), see cutlist


@dataclass
class DrillingSchedule:
    spec_name: str
    ops: list[DrillOp] = field(default_factory=list)

    @property
    def total_holes(self) -> int:
        return sum(len(op.holes) for op in self.ops)

    def to_csv(self) -> str:
        lines = ["id,part,operation,u_mm,v_mm,dia_mm,depth_mm,note"]
        for op in self.ops:
            for h in op.holes:
                lines.append(
                    f"{op.part_id},{op.part},{op.operation},{h.u:.1f},{h.v:.1f},"
                    f"{h.dia:.1f},{h.depth:.1f},{h.note}"
                )
        return "\n".join(lines)

    def report_text(self) -> str:
        lines = [f"Drilling schedule — {self.spec_name} "
                 f"({self.total_holes} holes)"]
        for op in self.ops:
            lines.append(f"  {op.part}: {op.operation} — {len(op.holes)} holes"
                         + (f"  ({op.note})" if op.note else ""))
        return "\n".join(lines)


GRID_TOL = 0.5  # mm slack when checking a hole pattern against the 32mm grid


def grid_violations(sched: "DrillingSchedule") -> list[str]:
    """Verify a drilling schedule conforms to the 32mm System (DIM-009).

    Checks every shelf-pin operation: holes within a row must step at the 32mm
    pitch and use the 5mm pin diameter. Returns a list of human-readable
    nonconformities (empty == grid-clean). A guard the compiler's own output
    should always pass, and a check for any externally supplied schedule.
    """
    out: list[str] = []
    for op in sched.ops:
        if "shelf-pin" not in op.operation:
            continue
        rows: dict[str, list[float]] = {}
        for h in op.holes:
            rows.setdefault(h.face, []).append(h.v)
            if abs(h.dia - PIN_DIA) > GRID_TOL:
                out.append(f"{op.part}: pin dia {h.dia:.1f}mm is not {PIN_DIA:.0f}mm")
        for row, vs in rows.items():
            vs = sorted(vs)
            for a, b in zip(vs, vs[1:], strict=False):
                if abs((b - a) - SYSTEM_PITCH) > GRID_TOL:
                    out.append(
                        f"{op.part}/{row}: {b - a:.1f}mm gap is off the "
                        f"{SYSTEM_PITCH:.0f}mm grid"
                    )
                    break
    return out




def _pin_heights(panel_h: float, max_holes: int = 400) -> list[float]:
    import math
    if not math.isfinite(panel_h) or panel_h <= 0:
        return []
    v = PIN_END_MARGIN
    out = []
    while v <= panel_h - PIN_END_MARGIN + GEOMETRY_EPSILON and len(out) < max_holes:
        out.append(round(v, 1))
        v += SYSTEM_PITCH
    return out


def _project_drilling(project: ComponentGroup) -> DrillingSchedule:
    """Combine each component's drilling schedule, part names tagged per cabinet.

    Hole positions are local to each part, so they don't depend on where the
    cabinet sits in the run — only the part labels are namespaced.
    """
    sched = DrillingSchedule(spec_name=project.name)
    for i, comp in enumerate(project.components, start=1):
        tag = component_tag(comp, i)
        for op in drilling_schedule(comp.spec).ops:
            sched.ops.append(DrillOp(
                part=f"{tag} · {op.part}", operation=op.operation,
                holes=op.holes, note=op.note,
                part_id=f"{tag}-{op.part_id}" if op.part_id else ""))
    return sched


def drilling_schedule(spec) -> DrillingSchedule:
    kind = spec_kind(spec)
    if kind == VOID:
        return DrillingSchedule(spec_name=spec.name)   # a gap bores nothing
    if kind == GROUP:
        return _project_drilling(spec)
    panels = panel_layout(spec)
    sched = DrillingSchedule(spec_name=spec.name)
    cl = generate_cutlist(spec)
    pid = cl.part_id_for_label   # resolve a panel label to its cut-list part ID

    brand = getattr(spec, "hardware_brand", "generic")
    # ``drawers`` is a list of Drawer on a cabinet but a plain count on the
    # legged types; either way map each to a side-mount slide for the schedule.
    _drawers = getattr(spec, "drawers", [])
    if isinstance(_drawers, int):
        slide_types = {i + 1: "side_mount" for i in range(_drawers)}
    else:
        slide_types = {i + 1: str(getattr(d, "slide_type", "side_mount"))
                       for i, d in enumerate(_drawers)}

    # Dispatch on the panel's typed role rather than re-deriving it from label
    # prefixes (the convention is decoded once in geometry.classify_panel_role).
    sides = [p for p in panels if p.role in (PanelRole.SIDE_LEFT, PanelRole.SIDE_RIGHT)]
    side_by_hand = {("R" if p.role is PanelRole.SIDE_RIGHT else "L"): p
                    for p in sides}
    drawer_fronts = sorted(
        [p for p in panels if p.role is PanelRole.DRAWER_FRONT],
        key=lambda p: p.label,
    )
    doors = [p for p in panels if p.role is PanelRole.DOOR]

    sched.ops.extend(_shelf_pin_ops(spec, sides, pid))
    sched.ops.extend(_slide_ops(sides, drawer_fronts, brand, slide_types, pid))
    sched.ops.extend(_hinge_ops(doors, sides, side_by_hand, pid))
    sched.ops.extend(_pocket_ops(spec, panels, pid))
    if kind in (NIGHTSTAND, DESK):
        sched.ops.extend(_legged_slide_ops(spec, panels, pid))
    if kind == WORKBENCH:
        sched.ops.extend(_dog_hole_ops(spec))
    return sched


def _legged_slide_ops(spec, panels, pid) -> list[DrillOp]:
    """Drawer-slide screw holes for an apron-hung (nightstand/desk) drawer.

    Each drawer rides a ball-bearing slide pair screwed to the side aprons (and,
    for a lower drawer, a runner level with it). The holes are mirrored on both
    sides, so one op per drawer captures the boring without claiming zero."""
    n = int(getattr(spec, "drawers", 0) or 0)
    if n <= 0:
        return []
    side_aprons = [p for p in panels if p.label == "Apron side"]
    if not side_aprons:
        return []
    _, depth_y, ah = side_aprons[0].size       # (thickness, depth, height)
    us = [37.0, round(depth_y / 2, 1), round(depth_y - 37.0, 1)]
    v = round(ah / 2, 1)
    ops: list[DrillOp] = []
    for di in range(1, n + 1):
        holes = [Hole("slide screw", u, v, 4.0, 12.0) for u in us]
        ops.append(DrillOp(
            part="Apron side", operation=f"drawer {di} slide screws",
            note="ball-bearing slide; mirror on both side aprons / runners",
            part_id=pid("Apron side"), holes=holes))
    return ops


def _pocket_ops(spec, panels, pid) -> list[DrillOp]:
    """Pocket-screw holes when the piece uses pocket joinery.

    A legged piece's aprons/rails are pocket-screwed into the legs: two angled
    pockets at each end of every apron. Bored with a pocket-hole jig, so the
    drilling schedule should list them rather than read as zero holes."""
    if str(getattr(spec, "joinery", "")).strip().lower() != "pocket":
        return []
    POCKET_DIA, POCKET_DEPTH = 9.5, 25.0
    ops: list[DrillOp] = []
    for p in panels:
        if getattr(p, "category", "") != "apron":
            continue
        sx, sy, sz = p.size
        length = max(sx, sy)
        v = sz / 2
        holes: list[Hole] = []
        for end_u in (30.0, round(length - 30.0, 1)):
            for dv in (-12.0, 12.0):       # two pockets stacked at each end
                holes.append(Hole("pocket", end_u, round(v + dv, 1),
                                  POCKET_DIA, POCKET_DEPTH,
                                  note="~15° pocket into the leg"))
        ops.append(DrillOp(
            part=p.label, operation="pocket-screw holes",
            note="2 pockets per end, drilled with a pocket-hole jig",
            part_id=pid(p.label), holes=holes))
    return ops


def _dog_hole_ops(spec) -> list[DrillOp]:
    """A row of bench-dog holes along the front of a workbench top."""
    n = int(getattr(spec, "dog_hole_count", 0) or 0)
    if n <= 0:
        return []
    dia = round(float(getattr(spec, "dog_hole_dia", 19.0)), 1)
    depth = round(float(getattr(spec, "top_thickness", 75.0)), 1)
    usable = spec.width - 2 * spec.leg_inset
    x0 = spec.leg_inset
    step = usable / (n - 1) if n > 1 else 0.0
    front_setback = 40.0          # dog row in from the front edge of the top
    holes = [Hole("dog hole", round(x0 + i * step, 1), front_setback, dia, depth,
                  note="through; align with the vise")
             for i in range(n)]
    return [DrillOp(
        part="Top (assembled)", operation=f"{n}x bench-dog holes",
        note=f"⌀{dia:.0f}mm row ~{round(step) if n > 1 else 150}mm spacing "
             "along the front", part_id="", holes=holes)]


def _shelf_pin_ops(spec, sides, pid) -> list[DrillOp]:
    """Two 32mm shelf-pin rows on each side panel (only if the cabinet has
    adjustable shelves)."""
    ops: list[DrillOp] = []
    if getattr(spec, "shelves", 0) <= 0:
        return ops
    for side in sides:
        _, depth, panel_h = side.size
        rows = {"front row": ROW_SETBACK, "back row": depth - ROW_SETBACK}
        op = DrillOp(part=side.label, operation="shelf-pin holes (32mm)",
                     note=f"2 rows @ {SYSTEM_PITCH:.0f}mm pitch",
                     part_id=pid(side.label))
        for row_name, u in rows.items():
            for v in _pin_heights(panel_h):
                op.holes.append(Hole(row_name, u, v, PIN_DIA, PIN_DEPTH))
        ops.append(op)
    return ops


def _slide_ops(sides, drawer_fronts, brand, slide_types, pid) -> list[DrillOp]:
    """Drawer-slide mounting on each side.

    Side-mount slides screw to a mid-height line; undermount slides mount low
    with a front bracket and a rear locking device (and the box gets a rear
    notch), so the boring differs by slide type.
    """
    ops: list[DrillOp] = []
    for side in sides:
        _, depth, panel_h = side.size
        side_bottom = side.center[2] - panel_h / 2
        for df in drawer_fronts:
            slide_v = df.center[2] - side_bottom        # height up the side
            idx = trailing_index(df.label)
            slide = select_slide(brand, slide_types.get(idx, "side_mount"))
            if slide.slide_type == "undermount":
                op = DrillOp(
                    part=side.label, operation=f"undermount slide — {df.label}",
                    note=f"{slide.name}; box needs a rear notch",
                    part_id=pid(side.label))
                # Front bracket (near the front) + rear locking device.
                low_v = max(slide_v - 30.0, 10.0)
                op.holes.append(Hole("front bracket", 37.0, low_v, 4.0, 12.0))
                op.holes.append(Hole("front bracket", 69.0, low_v, 4.0, 12.0))
                for k in range(slide.locking_holes):
                    op.holes.append(Hole("rear locking", depth - 37.0,
                                         low_v + k * SYSTEM_PITCH, 4.0, 12.0))
            else:
                op = DrillOp(
                    part=side.label, operation=f"slide line — {df.label}",
                    note=slide.name, part_id=pid(side.label))
                for d in SLIDE_SCREW_DEPTHS:
                    u = depth / 2 if d is None else (d if d > 0 else depth + d)
                    op.holes.append(Hole("slide screw", u, slide_v, 4.0, 12.0))
            ops.append(op)
    return ops


def _hinge_ops(doors, sides, side_by_hand, pid) -> list[DrillOp]:
    """Hinge cup bores on each door + the matching mounting-plate screws on the
    side the door hinges to."""
    ops: list[DrillOp] = []
    for door in doors:
        dw, _, dh = door.size
        n = hinge_count(dh)
        # Hinge edge: left door hinges left, right door hinges right.
        right_hung = door.label.endswith("R")
        u = (dw - HINGE_CUP_INSET) if right_hung else HINGE_CUP_INSET
        if n == 1:
            heights = [dh / 2]
        else:
            span = dh - 2 * HINGE_END_MARGIN
            heights = [HINGE_END_MARGIN + span * i / (n - 1) for i in range(n)]
        op = DrillOp(part=door.label, operation=f"{n}x hinge cup (35mm)",
                     note="cup centre from hinge edge", part_id=pid(door.label))
        for v in heights:
            op.holes.append(Hole("hinge cup", u, round(v, 1),
                                 HINGE_CUP_DIA, HINGE_CUP_DEPTH))
        ops.append(op)

        # Mounting-plate screws on the matching cabinet side, at each hinge
        # height: the plate sits on the side the door hinges to.
        side = side_by_hand.get("R" if right_hung else "L") \
            or (sides[0] if sides else None)
        if side is not None:
            _, sdepth, spanel_h = side.size
            side_bottom = side.center[2] - spanel_h / 2
            door_bottom = door.center[2] - dh / 2
            pop = DrillOp(
                part=side.label, operation=f"hinge plate screws — {door.label}",
                note="2 screws per hinge (32mm system)", part_id=pid(side.label))
            for v in heights:
                vv = round(door_bottom + v - side_bottom, 1)
                pop.holes.append(Hole("plate screw", PLATE_SCREW_INSET, vv, 4.0, 12.0))
                pop.holes.append(Hole("plate screw",
                                      PLATE_SCREW_INSET + SYSTEM_PITCH, vv, 4.0, 12.0))
            ops.append(pop)
    return ops


# --- placing bores into a part's outline ------------------------------------
# A hole is local to its panel face: ``v`` runs up the part's *length* (the
# longer cut-list dimension), ``u`` across its *width* (see the module docstring
# and ``Hole``). The nester may lay a part either way round on the sheet, so a
# consumer drawing the bores must map (u, v) into the placed rectangle honouring
# that rotation. These helpers do that once, so the nest DXF and the per-part
# shop drawings project bores identically.

def placement_rotated(part_length: float, part_width: float,
                      rect_l: float, rect_w: float) -> bool:
    """True if the part was laid width-along-the-sheet (rotated) when nested.

    Decided from the placed rectangle: ``rect_l`` (along the sheet length) maps
    to whichever part dimension it matches more closely.
    """
    return abs(rect_l - part_length) > abs(rect_l - part_width)


def place_rect(rotated: bool, x: float, y: float,
               a: float, b: float, da: float, db: float
               ) -> tuple[float, float, float, float]:
    """Map a local rectangle into a nest placement honouring the rotation.

    Mirrors :func:`place_holes`: when the part is nested *rotated* the ``a``/``da``
    axis runs along the sheet x-axis; otherwise ``b``/``db`` does. One swap rule
    shared by the nest DXF's cut-out and housing bands (and drawings), so the
    part-frame→sheet transform lives in exactly one place.
    """
    if rotated:
        return (x + a, y + b, da, db)
    return (x + b, y + a, db, da)


def place_holes(holes, part_length: float, part_width: float,
                ox: float, oy: float, rect_l: float, rect_w: float
                ) -> list[tuple[float, float, "Hole"]]:
    """Map local ``(u, v)`` *holes* into a placed rectangle at origin (ox, oy).

    The rectangle ``rect_l`` x ``rect_w`` is a nest placement (length along the
    sheet x-axis). Returns ``(cx, cy, hole)`` absolute centres. When the part is
    nested unrotated, ``v`` runs along the sheet x-axis and ``u`` along y; when
    rotated the two swap — so a bore always lands inside its part outline.
    """
    rotated = placement_rotated(part_length, part_width, rect_l, rect_w)
    out: list[tuple[float, float, Hole]] = []
    for h in holes:
        if rotated:                       # part.width runs along the sheet x-axis
            cx, cy = ox + h.u, oy + h.v
        else:                             # part.length runs along the sheet x-axis
            cx, cy = ox + h.v, oy + h.u
        out.append((cx, cy, h))
    return out


def holes_by_part_id(sched: "DrillingSchedule") -> dict[str, list["DrillOp"]]:
    """Group a schedule's ops by their shared cut-list ``part_id``."""
    out: dict[str, list[DrillOp]] = {}
    for op in sched.ops:
        if op.part_id:
            out.setdefault(op.part_id, []).append(op)
    return out


def ops_for_instance(ops: list["DrillOp"], instance: int, qty: int
                     ) -> list["DrillOp"]:
    """Pick the drilling ops belonging to one placed instance of a part.

    A part with qty>1 (two sides, a pair of doors) is bored per hand: the
    schedule carries one op-set per distinct ``op.part`` identity (e.g. "Side L"
    / "Side R"). When the number of identities equals the part qty we pair the
    1-based *instance* to the i-th identity; with a single identity every
    instance shares it. Any other shape is genuinely ambiguous from the nest
    label alone, so we skip it rather than risk boring the wrong hand.
    """
    identities: list[str] = []
    for op in ops:
        if op.part not in identities:
            identities.append(op.part)
    if len(identities) == 1:
        return list(ops)
    if len(identities) == qty and 1 <= instance <= qty:
        want = identities[instance - 1]
        return [op for op in ops if op.part == want]
    return []                              # ambiguous instance->hand mapping
