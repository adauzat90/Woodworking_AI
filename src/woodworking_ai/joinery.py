"""Joinery setup sheets: the actual machining dimensions.

A spec names a joint ("dado", "domino", a drawer "dovetail"); a shop needs the
*numbers* to set the saw or router: the cut width, depth, and where it sits.
This module turns the spec's joinery choices into a list of :class:`JoineryOp`
setup instructions, keyed by the same part IDs the cut list and drilling use.

Pure arithmetic — no CAD dependency. Conventions: a housed-joint depth is half
the stock thickness (the plywood convention; solid stock often uses a third),
and a dado/groove is cut to the *mating* panel's thickness so it seats snug.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import (CabinetSpec, TableSpec, ComponentGroup, BackStyle,
                  Joinery)
from .dispatch import spec_kind, VOID, GROUP, TABLE, CABINET
from . import furniture
from .cutlist import generate_cutlist
from .geometry import component_tag
from .constants import (
    DOOR_PANEL_GROOVE, HOUSED_DEPTH_FRACTION, GROOVE_BACK_INSET,
)


@dataclass
class JoineryOp:
    part: str
    operation: str            # e.g. "dado for bottom"
    tool: str                 # e.g. "dado stack / straight bit"
    width: float              # cut width (mm); 0 when not a width-defined cut
    depth: float              # cut depth (mm)
    reference: str = ""       # where it sits ("from bottom edge", "rear edge")
    part_id: str = ""
    note: str = ""


@dataclass
class JoinerySchedule:
    spec_name: str
    ops: list[JoineryOp] = field(default_factory=list)

    def to_csv(self) -> str:
        lines = ["id,part,operation,tool,width_mm,depth_mm,reference,note"]
        for o in self.ops:
            lines.append(
                f"{o.part_id},{o.part},{o.operation},{o.tool},"
                f"{o.width:.1f},{o.depth:.1f},{o.reference},{o.note}")
        return "\n".join(lines)

    def report_text(self) -> str:
        lines = [f"Joinery setup — {self.spec_name} ({len(self.ops)} ops)"]
        for o in self.ops:
            dims = f"{o.width:.0f}×{o.depth:.0f}mm" if o.width else f"{o.depth:.0f}mm deep"
            lines.append(f"  {o.part}: {o.operation} — {o.tool}, {dims}"
                         + (f" ({o.reference})" if o.reference else ""))
        return "\n".join(lines)


def _housed_joint(joint: Joinery, mating_thickness: float, stock: float
                  ) -> tuple[str, float, float, str]:
    """(tool, width, depth, note) for a carcass panel-into-side joint."""
    depth = round(stock * HOUSED_DEPTH_FRACTION, 1)
    j = str(joint).lower()
    if j == "dado":
        return ("dado stack / straight bit", round(mating_thickness, 1), depth,
                "cut to the mating panel thickness for a snug fit")
    if j == "rabbet":
        return ("rabbet bit / dado", round(mating_thickness, 1), depth,
                "rabbet at the panel end")
    if j == "dowel":
        return ("doweling jig (8mm)", 8.0, 30.0,
                "8mm dowels ~64mm on centre")
    if j == "domino":
        return ("Festool Domino (5mm)", 5.0, 25.0, "tenons ~128mm on centre")
    if j == "pocket":
        return ("pocket-hole jig", 0.0, 0.0, "pocket screws from the inside face")
    if j == "screw":
        return ("drill (pilot)", 0.0, 0.0, "pilot + countersink, glue optional")
    return ("drill / glue", 0.0, 0.0, "butt joint — weak; prefer a housed joint")


def _cabinet_joinery(spec: CabinetSpec, cl) -> list[JoineryOp]:
    m = spec.material
    pid = cl.part_id_for_label
    ops: list[JoineryOp] = []
    tool, width, depth, note = _housed_joint(spec.joinery, m.carcass, m.carcass)

    # Sides receive the bottom (and a full top, where present).
    for side_label in ("Side L", "Side R"):
        ops.append(JoineryOp(
            part=side_label, operation="joint for bottom", tool=tool,
            width=width, depth=depth, reference="near the bottom edge",
            part_id=pid("Side"), note=note))
        if spec.has_full_top:
            ops.append(JoineryOp(
                part=side_label, operation="joint for top", tool=tool,
                width=width, depth=depth, reference="at the top edge",
                part_id=pid("Side"), note=note))

    # Back capture: a rabbet or a grooved housing (applied backs need no cut).
    if spec.back == BackStyle.RABBETED:
        ops.append(JoineryOp(
            part="Side / top / bottom", operation="rabbet for back",
            tool="rabbet bit / dado", width=round(m.back, 1),
            depth=round(m.back, 1), reference="rear edge",
            part_id=pid("Side"), note="back sits flush in the rabbet"))
    elif spec.back == BackStyle.GROOVED:
        ops.append(JoineryOp(
            part="Side / top / bottom", operation="groove for back",
            tool="straight bit / dado", width=round(m.back, 1),
            depth=round(m.carcass * HOUSED_DEPTH_FRACTION, 1),
            reference=f"{GROOVE_BACK_INSET:.0f}mm in from the rear edge",
            part_id=pid("Side"), note="back captured in the groove"))

    # Five-piece doors are coped-and-sticked with a panel groove.
    style = str(getattr(spec, "door_style", "slab")).lower()
    if spec.doors and style != "slab":
        ops.append(JoineryOp(
            part="Door stile/rail", operation="cope-and-stick + panel groove",
            tool="rail-and-stile router set", width=round(m.door_panel, 1),
            depth=round(DOOR_PANEL_GROOVE, 1), reference="frame inner edge",
            part_id=pid("Door stile"),
            note="cope the rail ends to the stile sticking; panel floats"))

    # Face-frame stiles/rails (solid) are typically pocket/domino/dowel joined.
    if spec.construction.value == "face_frame":
        ops.append(JoineryOp(
            part="Face-frame stile/rail", operation="frame joint",
            tool="pocket-hole jig / Domino", width=0.0, depth=0.0,
            reference="stile-to-rail", part_id=pid("Face-frame stile"),
            note="2 pocket screws or one 5×30 Domino per joint"))

    # Drawer-box corners.
    for i, dr in enumerate(spec.drawers, start=1):
        if dr.false_front:
            continue
        cj = str(dr.corner_joint).lower()
        label = f"Drawer {i} box"
        box_pid = pid(f"Drawer {i} box side")
        if cj == "dovetail":
            ops.append(JoineryOp(
                part=label, operation="dovetail corners",
                tool="dovetail jig / saw", width=0.0,
                depth=round(m.drawer_box, 1),
                reference="tails on the sides", part_id=box_pid,
                note="tails on the sides so the front can't pull off"))
        elif cj == "box":
            ops.append(JoineryOp(
                part=label, operation="box/finger joint",
                tool="box-joint jig", width=round(m.drawer_box, 1),
                depth=round(m.drawer_box, 1), reference="corners",
                part_id=box_pid, note="finger width = box stock thickness"))
        elif cj in ("rabbet", "locking_rabbet"):
            ops.append(JoineryOp(
                part=label, operation=f"{cj.replace('_', ' ')} corners",
                tool="dado / router", width=round(m.drawer_box, 1),
                depth=round(m.drawer_box * 0.5, 1), reference="corners",
                part_id=box_pid, note="glue + brad the rabbet"))
        else:
            ops.append(JoineryOp(
                part=label, operation=f"{cj} corners", tool="doweling jig / glue",
                width=0.0, depth=0.0, reference="corners", part_id=box_pid,
                note="weak corner; prefer dovetail/box/locking rabbet"))
        # The drawer bottom rides in a groove in the box sides.
        ops.append(JoineryOp(
            part=f"{label} sides", operation="groove for bottom",
            tool="straight bit / dado", width=round(m.back, 1),
            depth=round(m.drawer_box * 0.5, 1),
            reference="~10mm up from the bottom edge", part_id=box_pid))

    return ops


def _table_joinery(spec: TableSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    j = str(spec.joinery).lower()
    if j == "mortise_tenon":
        tool, w, d, note = ("mortiser / saw", round(spec.apron_thickness / 3, 1),
                            round(spec.leg * 0.6, 1), "haunched M&T into the leg")
    elif j == "domino":
        tool, w, d, note = ("Festool Domino (10mm)", 10.0, 28.0,
                            "two 10×50 Dominoes per leg-apron joint")
    elif j == "dowel":
        tool, w, d, note = ("doweling jig (10mm)", 10.0, 30.0,
                            "two 10mm dowels per joint + corner block")
    else:
        tool, w, d, note = ("pocket-hole jig", 0.0, 0.0,
                            "pocket screws + glue blocks (racks more than M&T)")
    return [JoineryOp(
        part="Leg / apron", operation="leg-to-apron joint", tool=tool,
        width=w, depth=d, reference="apron into leg", part_id=pid("Leg"),
        note=note)]


def _project_joinery(project: ComponentGroup) -> JoinerySchedule:
    sched = JoinerySchedule(spec_name=project.name)
    for i, comp in enumerate(project.components, start=1):
        tag = component_tag(comp, i)
        for op in joinery_schedule(comp.spec).ops:
            sched.ops.append(JoineryOp(
                part=f"{tag} · {op.part}", operation=op.operation, tool=op.tool,
                width=op.width, depth=op.depth, reference=op.reference,
                part_id=f"{tag}-{op.part_id}" if op.part_id else "",
                note=op.note))
    return sched


def joinery_schedule(spec) -> JoinerySchedule:
    """Setup sheet of machining ops for a leaf, or aggregate a group.

    VOID/GROUP are handled here; every *leaf* type dispatches its machining ops
    through the :mod:`furniture` registry, so a new furniture type adds joinery
    by registering, not by editing this function.
    """
    kind = spec_kind(spec)
    if kind == VOID:
        return JoinerySchedule(spec_name=spec.name)   # a gap has no joinery
    if kind == GROUP:
        return _project_joinery(spec)
    cl = generate_cutlist(spec)
    ops = furniture.get(kind).joinery_ops(spec, cl)
    return JoinerySchedule(spec_name=spec.name, ops=ops)


# Register the built-in leaf joinery. Cabinets (including the diagonal corner)
# use the housed box joints; tables use the leg-to-apron joint. A new furniture
# type registers its own ``joinery_ops`` and routes with no edit here.
furniture.register(CABINET, joinery_ops=_cabinet_joinery)
furniture.register(TABLE, joinery_ops=_table_joinery)
