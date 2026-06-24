"""Cut list + hardware schedule generation.

Turns a validated :class:`CabinetSpec` into the parts a shop actually cuts and
the hardware they buy. This is pure arithmetic — no CAD dependency — so it is
fast, deterministic, and fully unit-testable. It models a **frameless base
cabinet**.

Conventions: every dimension is in the spec's units (mm by default). For each
panel, ``length`` is the longer face dimension and ``width`` the shorter; this
is the convention a cut list / nesting tool expects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .dsl import CabinetSpec, TableSpec, BackStyle, Construction, CabinetType
from .geometry import front_plan
# Construction constants now live in one neutral module shared with geometry.
from .constants import (
    SHELF_SIDE_CLEARANCE, SHELF_SETBACK, STRETCHER_WIDTH,
    FRAME_WIDTH, FRAME_THICKNESS,
    SLIDE_SIDE_CLEARANCE, DRAWER_BOX_HEIGHT_DROP, DRAWER_BOX_DEPTH_GAP,
)


@dataclass
class Part:
    name: str
    qty: int
    length: float
    width: float
    thickness: float
    material: str = "sheet"
    grain: str = "length"      # grain direction runs along `length`
    notes: str = ""

    @property
    def area_m2(self) -> float:
        """Single-part face area in m² (assumes mm input)."""
        return (self.length / 1000.0) * (self.width / 1000.0)


@dataclass
class Hardware:
    name: str
    qty: int
    notes: str = ""


@dataclass
class CutList:
    spec_name: str
    parts: list[Part] = field(default_factory=list)
    hardware: list[Hardware] = field(default_factory=list)

    @property
    def sheet_area_m2(self) -> float:
        """Total face area of all panels (gross, before nesting waste)."""
        return sum(p.area_m2 * p.qty for p in self.parts)

    def to_csv(self) -> str:
        lines = ["part,qty,length_mm,width_mm,thickness_mm,material,grain,notes"]
        for p in self.parts:
            lines.append(
                f"{p.name},{p.qty},{p.length:.1f},{p.width:.1f},"
                f"{p.thickness:.1f},{p.material},{p.grain},{p.notes}"
            )
        return "\n".join(lines)

    def hardware_csv(self) -> str:
        lines = ["item,qty,notes"]
        for h in self.hardware:
            lines.append(f"{h.name},{h.qty},{h.notes}")
        return "\n".join(lines)

    def summary(self) -> str:
        n_panels = sum(p.qty for p in self.parts)
        n_hw = sum(h.qty for h in self.hardware)
        return (
            f"{self.spec_name}: {n_panels} panels "
            f"({len(self.parts)} unique), {n_hw} hardware items, "
            f"~{self.sheet_area_m2:.2f} m² sheet goods"
        )


def _add_drawer_box(cl: "CutList", spec: CabinetSpec, index: int,
                    opening_w: float, front_height: float,
                    interior_depth: float) -> None:
    """Append the four box panels + bottom for one drawer."""
    m = spec.material
    t = m.drawer_box
    box_w = opening_w - 2 * SLIDE_SIDE_CLEARANCE          # outer box width
    box_h = max(front_height - DRAWER_BOX_HEIGHT_DROP, 60.0)
    box_d = max(interior_depth - DRAWER_BOX_DEPTH_GAP, 100.0)
    cl.parts.append(Part(
        f"Drawer {index} box side", 2, length=box_d, width=box_h, thickness=t,
        material="drawer box", notes="grooved for bottom",
    ))
    cl.parts.append(Part(
        f"Drawer {index} box front/back", 2, length=box_w - 2 * t, width=box_h,
        thickness=t, material="drawer box",
    ))
    cl.parts.append(Part(
        f"Drawer {index} box bottom", 1, length=box_w, width=box_d,
        thickness=m.back, material="back panel", notes="captured in groove",
    ))


def _diagonal_cutlist(spec: CabinetSpec) -> CutList:
    """Parts + hardware for a diagonal (angled-front) corner cabinet."""
    m = spec.material
    cl = CutList(spec_name=spec.name)
    W, D, t, c = spec.width, spec.depth, m.carcass, spec.corner_cut
    toe_h = spec.toe_kick_height
    box_h = spec.box_height
    front_w = (W / 2 - c) - (-W / 2 + t)

    cl.parts.append(Part("Side L", 1, length=box_h, width=D, thickness=t,
                         notes="full gable"))
    cl.parts.append(Part("Side R", 1, length=box_h, width=D - c, thickness=t,
                         notes="short gable (chamfer)"))
    cl.parts.append(Part("Back", 1, length=box_h, width=W - 2 * t, thickness=t))
    cl.parts.append(Part("Front rail", 1, length=box_h, width=front_w, thickness=t))
    cl.parts.append(Part("Bottom", 1, length=W - 2 * t, width=D - 2 * t,
                         thickness=t, notes="trim front-right corner"))
    cl.parts.append(Part("Top", 1, length=W - 2 * t, width=D - 2 * t,
                         thickness=t, notes="trim front-right corner"))
    if spec.toe_kick and toe_h > 0:
        cl.parts.append(Part("Toe kick", 1, length=W, width=toe_h, thickness=t))
    if spec.shelves > 0:
        cl.parts.append(Part("Corner shelf", spec.shelves, length=W - 2 * t - 4,
                             width=D - 2 * t - 4, thickness=m.shelf,
                             notes="trim to corner"))
        cl.hardware.append(Hardware("Shelf pin", spec.shelves * 4, "5mm"))
    door_len = max(c * math.sqrt(2) - 2 * spec.reveal, 50.0)
    cl.parts.append(Part("Door", 1, length=box_h - 2 * spec.reveal, width=door_len,
                         thickness=m.door, material="door/front",
                         notes="angled 45° door"))
    cl.hardware.append(Hardware("Concealed hinge", 2, "soft-close"))
    cl.hardware.append(Hardware("Door pull", 1))
    if spec.edge_banding:
        cl.hardware.append(Hardware("Edge banding", 1, f"~{2 * box_h / 1000:.1f} m"))
    return cl


def _table_cutlist(spec: TableSpec) -> CutList:
    """Parts + hardware for a four-legged table."""
    cl = CutList(spec_name=spec.name)
    leg_h = spec.height - spec.top_thickness
    li, leg = spec.leg_inset, spec.leg
    apron_x = (spec.width - 2 * li - leg) - leg
    apron_y = (spec.depth - 2 * li - leg) - leg
    cl.parts.append(Part("Top", 1, length=spec.width, width=spec.depth,
                         thickness=spec.top_thickness, material="top",
                         notes="glued panel or solid"))
    cl.parts.append(Part("Leg", 4, length=leg_h, width=leg, thickness=leg,
                         material="leg", notes="square stock"))
    cl.parts.append(Part("Apron (long)", 2, length=apron_x, width=spec.apron_height,
                         thickness=spec.apron_thickness, material="apron"))
    cl.parts.append(Part("Apron (short)", 2, length=apron_y, width=spec.apron_height,
                         thickness=spec.apron_thickness, material="apron"))
    cl.hardware.append(Hardware("Corner bracket", 4, "leg-to-apron"))
    cl.hardware.append(Hardware("Tabletop fastener", 8, "expansion clip"))
    return cl


def generate_cutlist(spec) -> CutList:
    """Derive the full parts + hardware list for a cabinet or table."""
    if isinstance(spec, TableSpec):
        return _table_cutlist(spec)
    if spec.cabinet_type == CabinetType.CORNER_DIAGONAL:
        return _diagonal_cutlist(spec)

    m = spec.material
    cl = CutList(spec_name=spec.name)

    toe_h = spec.toe_kick_height
    box_height = spec.box_height
    interior_width = spec.interior_width
    interior_depth = spec.interior_depth  # back recessed by its thickness

    # ---- carcass --------------------------------------------------------
    cl.parts.append(Part(
        "Side", 2, length=box_height, width=spec.depth, thickness=m.carcass,
        grain="length", notes="full-height gable",
    ))
    cl.parts.append(Part(
        "Bottom", 1, length=interior_width, width=interior_depth,
        thickness=m.carcass, notes="between sides",
    ))
    # Wall/tall cabinets are enclosed with a full top panel; base cabinets use
    # two top rails, leaving room for a sink/drawers and to fasten the counter.
    if spec.has_full_top:
        cl.parts.append(Part(
            "Top", 1, length=interior_width, width=interior_depth,
            thickness=m.carcass, notes="enclosed top",
        ))
    else:
        cl.parts.append(Part(
            "Top stretcher", 2, length=interior_width, width=STRETCHER_WIDTH,
            thickness=m.carcass, notes="front & back top rail",
        ))

    # ---- back -----------------------------------------------------------
    if spec.back == BackStyle.APPLIED:
        back_l, back_w = box_height, spec.width
        back_note = "applied to rear edges"
    else:  # rabbeted / grooved: captured between the sides
        back_l, back_w = box_height - m.carcass, interior_width
        back_note = f"{spec.back.value} back"
    cl.parts.append(Part(
        "Back", 1, length=max(back_l, back_w), width=min(back_l, back_w),
        thickness=m.back, material="back panel", notes=back_note,
    ))

    # ---- shelves --------------------------------------------------------
    if spec.shelves > 0:
        shelf_w = interior_width - 2 * SHELF_SIDE_CLEARANCE
        shelf_d = interior_depth - SHELF_SETBACK
        cl.parts.append(Part(
            "Adjustable shelf", spec.shelves,
            length=shelf_w, width=shelf_d, thickness=m.shelf,
            notes="on shelf pins",
        ))
        cl.hardware.append(Hardware("Shelf pin", spec.shelves * 4, "5mm"))

    # ---- toe kick -------------------------------------------------------
    if spec.toe_kick and toe_h > 0:
        cl.parts.append(Part(
            "Toe kick", 1, length=spec.width, width=toe_h, thickness=m.carcass,
            notes=f"set back {spec.toe_kick.setback:.0f}mm",
        ))

    # ---- face frame (solid hardwood stiles + rails) ---------------------
    is_ff = spec.construction == Construction.FACE_FRAME
    if is_ff:
        cl.parts.append(Part(
            "Face-frame stile", 2, length=box_height, width=FRAME_WIDTH,
            thickness=FRAME_THICKNESS, material="frame", grain="length",
            notes="vertical, hardwood",
        ))
        cl.parts.append(Part(
            "Face-frame rail", 2, length=spec.width - 2 * FRAME_WIDTH,
            width=FRAME_WIDTH, thickness=FRAME_THICKNESS, material="frame",
            notes="top & bottom, hardwood",
        ))

    # ---- fronts: doors, drawers, mullion, blind filler ------------------
    # Sizes/positions come from the shared front_plan (also drives geometry), so
    # the parts list and the 3D model can never disagree about the fronts.
    plan = front_plan(spec)
    front_note = "inset" if is_ff else "overlay"

    filler = next((it for it in plan.items if it.kind == "filler"), None)
    if filler is not None:
        cl.parts.append(Part(
            "Blind filler", 1, length=filler.height, width=filler.width,
            thickness=filler.thickness, material="door/front",
            notes="covers blind return",
        ))

    for dr in plan.drawers:
        note = "false front" if dr.false_front else front_note
        cl.parts.append(Part(
            f"Drawer front #{dr.index}", 1,
            length=dr.width, width=dr.height, thickness=dr.thickness,
            material="door/front", notes=note,
        ))
        if dr.false_front:
            continue  # fixed panel: no box, no slides
        # The drawer box itself, sized for slide and depth clearance.
        _add_drawer_box(cl, spec, dr.index, plan.opening_w, dr.height,
                        interior_depth)
        cl.hardware.append(Hardware("Drawer slide (pair)", 1, "ball-bearing"))
        cl.hardware.append(Hardware("Drawer pull", 1))

    mullion = plan.mullion
    if mullion is not None:
        if is_ff:
            cl.parts.append(Part(
                "Face-frame center stile", 1, length=mullion.height,
                width=mullion.width, thickness=mullion.thickness,
                material="frame", notes="between doors",
            ))
        else:
            cl.parts.append(Part(
                "Mullion", 1, length=mullion.height, width=mullion.width,
                thickness=mullion.thickness, material="door/front",
                notes="center post",
            ))

    doors = plan.doors
    if doors:
        d0 = doors[0]
        cl.parts.append(Part(
            "Door", len(doors), length=d0.height, width=d0.width,
            thickness=d0.thickness, material="door/front",
            notes=f"{front_note} ({len(doors)})",
        ))
        cl.hardware.append(Hardware("Concealed hinge", len(doors) * 2, "soft-close"))
        cl.hardware.append(Hardware("Door pull", len(doors)))

    # ---- edge banding (rough running length on exposed front edges) -----
    if spec.edge_banding:
        # Front edges of the two sides + bottom + stretcher front.
        banding_mm = 2 * box_height + interior_width
        cl.hardware.append(Hardware(
            "Edge banding", 1, f"~{banding_mm/1000:.1f} m to match carcass",
        ))

    return cl
