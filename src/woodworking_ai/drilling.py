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
from .geometry import panel_layout, component_tag

# 32 mm System and boring constants (mm).
SYSTEM_PITCH = 32.0
PIN_DIA = 5.0
PIN_DEPTH = 12.0
ROW_SETBACK = 37.0          # each pin row in from the front / back edge
PIN_END_MARGIN = 64.0       # first/last pin in from the panel ends
HINGE_CUP_DIA = 35.0
HINGE_CUP_DEPTH = 12.5
HINGE_CUP_INSET = 22.5      # cup centre in from the hinge edge
HINGE_END_MARGIN = 90.0     # top/bottom hinge in from the door ends
SLIDE_SCREW_DEPTHS = (37.0, 0.5, -50.0)  # 0.5 means "mid-depth" sentinel


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


@dataclass
class DrillingSchedule:
    spec_name: str
    ops: list[DrillOp] = field(default_factory=list)

    @property
    def total_holes(self) -> int:
        return sum(len(op.holes) for op in self.ops)

    def to_csv(self) -> str:
        lines = ["part,operation,u_mm,v_mm,dia_mm,depth_mm,note"]
        for op in self.ops:
            for h in op.holes:
                lines.append(
                    f"{op.part},{op.operation},{h.u:.1f},{h.v:.1f},"
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
            for a, b in zip(vs, vs[1:]):
                if abs((b - a) - SYSTEM_PITCH) > GRID_TOL:
                    out.append(
                        f"{op.part}/{row}: {b - a:.1f}mm gap is off the "
                        f"{SYSTEM_PITCH:.0f}mm grid"
                    )
                    break
    return out


def hinge_count(door_height: float) -> int:
    """Number of concealed hinges for a door of this height."""
    if door_height <= 900:
        return 2
    if door_height <= 1600:
        return 3
    if door_height <= 2000:
        return 4
    return 5


def _pin_heights(panel_h: float, max_holes: int = 400) -> list[float]:
    import math
    if not math.isfinite(panel_h) or panel_h <= 0:
        return []
    v = PIN_END_MARGIN
    out = []
    while v <= panel_h - PIN_END_MARGIN + 1e-6 and len(out) < max_holes:
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
            sched.ops.append(DrillOp(part=f"{tag} · {op.part}",
                                     operation=op.operation, holes=op.holes,
                                     note=op.note))
    return sched


def drilling_schedule(spec) -> DrillingSchedule:
    if isinstance(spec, ComponentGroup):
        return _project_drilling(spec)
    panels = panel_layout(spec)
    sched = DrillingSchedule(spec_name=spec.name)

    sides = [p for p in panels if p.label.startswith("Side")]
    drawer_fronts = sorted(
        [p for p in panels if p.label.startswith("Drawer front")],
        key=lambda p: p.label,
    )
    doors = [p for p in panels if p.label == "Door"
             or p.label.startswith("Door ")]

    # --- shelf-pin rows on each side -------------------------------------
    if getattr(spec, "shelves", 0) > 0:
        for side in sides:
            _, depth, panel_h = side.size
            rows = {"front row": ROW_SETBACK, "back row": depth - ROW_SETBACK}
            op = DrillOp(part=side.label, operation="shelf-pin holes (32mm)",
                         note=f"2 rows @ {SYSTEM_PITCH:.0f}mm pitch")
            for row_name, u in rows.items():
                for v in _pin_heights(panel_h):
                    op.holes.append(Hole(row_name, u, v, PIN_DIA, PIN_DEPTH))
            sched.ops.append(op)

    # --- drawer-slide mounting lines on each side ------------------------
    for side in sides:
        _, depth, panel_h = side.size
        side_bottom = side.center[2] - panel_h / 2
        for df in drawer_fronts:
            slide_v = df.center[2] - side_bottom        # height up the side
            op = DrillOp(part=side.label,
                         operation=f"slide line — {df.label}",
                         note="ball-bearing slide")
            for d in SLIDE_SCREW_DEPTHS:
                u = depth / 2 if d == 0.5 else (d if d > 0 else depth + d)
                op.holes.append(Hole("slide screw", u, slide_v, 4.0, 12.0))
            sched.ops.append(op)

    # --- hinge cup bores on each door ------------------------------------
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
                     note="cup centre from hinge edge")
        for v in heights:
            op.holes.append(Hole("hinge cup", u, round(v, 1),
                                 HINGE_CUP_DIA, HINGE_CUP_DEPTH))
        sched.ops.append(op)

    return sched
