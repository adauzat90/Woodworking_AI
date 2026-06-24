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

from dataclasses import dataclass, field

from .dsl import CabinetSpec, BackStyle, Construction

# Small construction constants (mm). Centralised so they are easy to tune.
SHELF_SIDE_CLEARANCE = 2.0     # gap each side so an adjustable shelf drops in
SHELF_SETBACK = 20.0           # shelf shallower than interior depth
STRETCHER_WIDTH = 80.0         # front/back top rails on a base cabinet
BACK_RABBET = 0.0              # rabbeted back recess captured via interior depth
FRAME_WIDTH = 38.0             # face-frame stile/rail width (solid hardwood)
FRAME_THICKNESS = 19.0         # face-frame stock thickness
SLIDE_SIDE_CLEARANCE = 13.0    # gap each side for ball-bearing slides
DRAWER_BOX_HEIGHT_DROP = 40.0  # box height below the drawer front
DRAWER_BOX_DEPTH_GAP = 25.0    # box shallower than the interior


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
                    opening_w: float, dr, interior_depth: float) -> None:
    """Append the four box panels + bottom for one drawer."""
    m = spec.material
    t = m.drawer_box
    box_w = opening_w - 2 * SLIDE_SIDE_CLEARANCE          # outer box width
    box_h = max(dr.front_height - DRAWER_BOX_HEIGHT_DROP, 60.0)
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


def generate_cutlist(spec: CabinetSpec) -> CutList:
    """Derive the full parts + hardware list for a frameless base cabinet."""
    m = spec.material
    cl = CutList(spec_name=spec.name)

    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    box_height = spec.height - toe_h
    interior_width = spec.width - 2 * m.carcass
    interior_depth = spec.depth - m.back  # back recessed by its thickness

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
    else:  # rabbeted / grooved: captured inside the box
        back_l, back_w = box_height - m.carcass, interior_width + 2 * m.carcass
        back_w = interior_width  # sits between sides
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

    # ---- fronts: drawers stack at the top, doors fill the rest ----------
    # Face-frame fronts are inset in the frame opening; frameless are overlay.
    opening_w = (spec.width - 2 * FRAME_WIDTH) if is_ff else spec.width
    region_h = (box_height - 2 * FRAME_WIDTH) if is_ff else box_height
    front_note = "inset" if is_ff else "overlay"

    drawer_band = 0.0
    for i, dr in enumerate(spec.drawers, start=1):
        front_w = opening_w - 2 * spec.reveal
        note = "false front" if dr.false_front else front_note
        cl.parts.append(Part(
            f"Drawer front #{i}", 1,
            length=front_w, width=dr.front_height, thickness=m.door,
            material="door/front", notes=note,
        ))
        drawer_band += dr.front_height + spec.reveal
        if dr.false_front:
            continue  # fixed panel: no box, no slides
        # The drawer box itself, sized for slide and depth clearance.
        _add_drawer_box(cl, spec, i, opening_w, dr, interior_depth)
        cl.hardware.append(Hardware("Drawer slide (pair)", 1, "ball-bearing"))
        cl.hardware.append(Hardware("Drawer pull", 1))

    door_region = region_h - drawer_band
    if spec.doors > 0 and door_region > 0:
        door_h = door_region - 2 * spec.reveal
        if spec.doors == 1:
            door_w = opening_w - 2 * spec.reveal
        else:  # two doors share the opening with a center reveal
            door_w = (opening_w - 3 * spec.reveal) / 2
        cl.parts.append(Part(
            "Door", spec.doors, length=door_h, width=door_w, thickness=m.door,
            material="door/front", notes=f"{front_note} ({spec.doors})",
        ))
        cl.hardware.append(Hardware("Concealed hinge", spec.doors * 2, "soft-close"))
        cl.hardware.append(Hardware("Door pull", spec.doors))

    # ---- edge banding (rough running length on exposed front edges) -----
    if spec.edge_banding:
        # Front edges of the two sides + bottom + stretcher front.
        banding_mm = 2 * box_height + interior_width
        cl.hardware.append(Hardware(
            "Edge banding", 1, f"~{banding_mm/1000:.1f} m to match carcass",
        ))

    return cl
