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
from enum import Enum

from .dsl import (CabinetSpec, TableSpec, ComponentGroup, BackStyle,
                  Joinery, ShelfJoint, joinery_key)
from .dispatch import spec_kind, VOID, GROUP, TABLE, CABINET
from . import furniture
from .cutlist import generate_cutlist
from .geometry import component_tag
from .constants import (
    DOOR_PANEL_GROOVE, HOUSED_DEPTH_FRACTION, GROOVE_BACK_INSET,
)


class JoineryEdge(Enum):
    """Which edge/region of a panel a housed joint's ``reference`` points at.

    The reference is free text ("near the rear edge", "from the bottom"); both the
    B-Rep builder and the DXF nester need to know *which* edge it houses against
    to place the cut. Decoding that lived as duplicated ``"rear" in ref`` /
    ``"top" in ref`` substring ladders in :mod:`builder` and :mod:`dxf`; it now
    lives once in :func:`classify_joinery_edge`, and they dispatch on this enum.
    """

    REAR = "rear"
    TOP = "top"
    BOTTOM = "bottom"
    OTHER = "other"


def classify_joinery_edge(reference: str) -> JoineryEdge:
    """Decode a :attr:`JoineryOp.reference` to the panel edge it houses against.

    The one place the reference-text convention is read. Order matters and
    mirrors the original ladders: rear/back first, then top, then bottom, else an
    unlocated housing (a drawer-bottom groove or a generic cut).
    """
    ref = (reference or "").lower()
    if "rear" in ref or "back" in ref:
        return JoineryEdge.REAR
    if "top" in ref:
        return JoineryEdge.TOP
    if "bottom" in ref:
        return JoineryEdge.BOTTOM
    return JoineryEdge.OTHER


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


# --- joint geometry, data-driven -------------------------------------------
# Each joint name (the spec's lower-cased enum value) maps to its machining
# numbers, so adding/retuning a joint is a one-line data edit, not a new branch.

# Housed carcass joints whose *width* follows the mating panel thickness and
# *depth* follows the stock (computed in _housed_joint): name -> (tool, note).
_HOUSED_MATING = {
    "dado": ("dado stack / straight bit",
             "cut to the mating panel thickness for a snug fit"),
    "rabbet": ("rabbet bit / dado", "rabbet at the panel end"),
}
# Carcass joints with a fixed tool geometry: name -> (tool, width, depth, note).
_HOUSED_FIXED = {
    "dowel": ("doweling jig (8mm)", 8.0, 30.0, "8mm dowels ~64mm on centre"),
    "domino": ("Festool Domino (5mm)", 5.0, 25.0, "tenons ~128mm on centre"),
    "pocket": ("pocket-hole jig", 0.0, 0.0, "pocket screws from the inside face"),
    "screw": ("drill (pilot)", 0.0, 0.0, "pilot + countersink, glue optional"),
}
_HOUSED_BUTT = ("drill / glue", 0.0, 0.0,
                "butt joint — weak; prefer a housed joint")


def _housed_joint(joint: Joinery, mating_thickness: float, stock: float
                  ) -> tuple[str, float, float, str]:
    """(tool, width, depth, note) for a carcass panel-into-side joint."""
    j = str(joint).lower()
    if j in _HOUSED_MATING:
        tool, note = _HOUSED_MATING[j]
        return (tool, round(mating_thickness, 1),
                round(stock * HOUSED_DEPTH_FRACTION, 1), note)
    return _HOUSED_FIXED.get(j, _HOUSED_BUTT)


# Drawer-box corner joints: name -> (operation, tool, width×, depth×, reference,
# note). The width/depth multipliers scale the box stock thickness (0 = not a
# width-defined cut). ``{cj}`` in an operation is filled with the joint name.
_DRAWER_CORNER = {
    "dovetail": ("dovetail corners", "dovetail jig / saw", 0.0, 1.0,
                 "tails on the sides",
                 "tails on the sides so the front can't pull off"),
    "box": ("box/finger joint", "box-joint jig", 1.0, 1.0, "corners",
            "finger width = box stock thickness"),
    "rabbet": ("rabbet corners", "dado / router", 1.0, 0.5, "corners",
               "glue + brad the rabbet"),
    "locking_rabbet": ("locking rabbet corners", "dado / router", 1.0, 0.5,
                       "corners", "glue + brad the rabbet"),
}
_DRAWER_CORNER_DEFAULT = ("{cj} corners", "doweling jig / glue", 0.0, 0.0,
                          "corners",
                          "weak corner; prefer dovetail/box/locking rabbet")

# Table leg-to-apron joints with fixed geometry: name -> (tool, w, d, note).
# Mortise & tenon is spec-derived, so it is handled in _table_joinery.
_TABLE_JOINT = {
    "domino": ("Festool Domino (10mm)", 10.0, 28.0,
               "two 10×50 Dominoes per leg-apron joint"),
    "dowel": ("doweling jig (10mm)", 10.0, 30.0,
              "two 10mm dowels per joint + corner block"),
}
_TABLE_JOINT_DEFAULT = ("pocket-hole jig", 0.0, 0.0,
                        "pocket screws + glue blocks (racks more than M&T)")


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

    # Fixed shelves housed into the sides. Adjustable shelves (the default) ride
    # on pins and need no cut; screw/butt shelves aren't housed either (the
    # STRUCT-014 advisory flags those), so only dado/cleat add a setup op. The op
    # is a setup-sheet line (the shop cuts one housing per shelf height); its
    # "at each shelf height" reference classifies as OTHER, which the B-Rep
    # builder draws as a single representative housing rather than N at exact
    # heights — a known limitation of the reference-text geometry, shared by every
    # OTHER-classified op.
    sj = str(getattr(spec, "shelf_joint", ShelfJoint.PINS)).lower()
    if spec.shelves and sj == ShelfJoint.DADO:
        ops.append(JoineryOp(
            part="Side L / R", operation="dado for fixed shelf",
            tool="dado stack / straight bit", width=round(m.shelf, 1),
            depth=round(m.carcass * HOUSED_DEPTH_FRACTION, 1),
            reference="at each shelf height", part_id=pid("Side"),
            note=f"{spec.shelves} housed shelf/shelves — captured in shear"))
    elif spec.shelves and sj == ShelfJoint.CLEAT:
        ops.append(JoineryOp(
            part="Side L / R", operation="cleat for fixed shelf",
            tool="drill / glue", width=0.0, depth=0.0,
            reference="at each shelf height", part_id=pid("Side"),
            note=f"{spec.shelves} shelf/shelves rest on screwed-and-glued ledgers"))

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
        operation, tool, wx, dx, reference, note = _DRAWER_CORNER.get(
            cj, _DRAWER_CORNER_DEFAULT)
        ops.append(JoineryOp(
            part=label, operation=operation.format(cj=cj), tool=tool,
            width=round(m.drawer_box * wx, 1) if wx else 0.0,
            depth=round(m.drawer_box * dx, 1) if dx else 0.0,
            reference=reference, part_id=box_pid, note=note))
        # The drawer bottom rides in a groove in the box sides.
        ops.append(JoineryOp(
            part=f"{label} sides", operation="groove for bottom",
            tool="straight bit / dado", width=round(m.back, 1),
            depth=round(m.drawer_box * 0.5, 1),
            reference="~10mm up from the bottom edge", part_id=box_pid))

    return ops


def _table_joinery(spec: TableSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    j = joinery_key(spec)
    if j == "mortise_tenon":   # spec-derived geometry, not a fixed tool
        tool, w, d, note = ("mortiser / saw", round(spec.apron_thickness / 3, 1),
                            round(spec.leg * 0.6, 1), "haunched M&T into the leg")
    else:
        tool, w, d, note = _TABLE_JOINT.get(j, _TABLE_JOINT_DEFAULT)
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
