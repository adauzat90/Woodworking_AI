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

from .dsl import CabinetSpec
from .geometry import panel_layout

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


def hinge_count(door_height: float) -> int:
    """Number of concealed hinges for a door of this height."""
    if door_height <= 900:
        return 2
    if door_height <= 1600:
        return 3
    if door_height <= 2000:
        return 4
    return 5


def _pin_heights(panel_h: float) -> list[float]:
    v = PIN_END_MARGIN
    out = []
    while v <= panel_h - PIN_END_MARGIN + 1e-6:
        out.append(round(v, 1))
        v += SYSTEM_PITCH
    return out


def drilling_schedule(spec: CabinetSpec) -> DrillingSchedule:
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
    if spec.shelves > 0:
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
