"""Single source of truth for panel placement.

Both the geometry compiler (:mod:`builder`) and the Critic agent
(:mod:`agents.critic`) consume :func:`panel_layout`, so the 3D model and the
analytical checks can never drift apart. A :class:`PanelBox` is an axis-aligned
box in the shared frame:

    X = width  (left  -> right, 0 at center)
    Y = depth  (front -> back, 0 at the carcass front face)
    Z = height (floor -> up, 0 at the floor)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .dsl import (
    CabinetSpec, TableSpec, Project, BackStyle, Construction, CabinetType,
)

# Construction constants shared with the cut list (neutral module, no cycle).
from .constants import (
    STRETCHER_WIDTH, SHELF_SIDE_CLEARANCE, SHELF_SETBACK,
    FRAME_WIDTH, FRAME_THICKNESS, MULLION_WIDTH,
)


@dataclass
class PanelBox:
    """One placed panel. ``size`` and ``center`` are (x, y, z) triples.

    ``rot_z`` rotates the panel about the vertical (Z) axis through its centre,
    in degrees — used for the angled face/door of a diagonal corner cabinet.
    """

    label: str
    size: tuple[float, float, float]
    center: tuple[float, float, float]
    category: str = "carcass"   # carcass | back | shelf | toe | front | frame
    rot_z: float = 0.0
    oversized: bool = False     # a blank trimmed to shape on site (corner units)

    @property
    def is_front(self) -> bool:
        return self.category == "front"

    @property
    def is_rotated(self) -> bool:
        return abs(self.rot_z) > 1e-9

    def bounds(self) -> tuple[tuple[float, float], ...]:
        """Axis-aligned bounds ((xmin, xmax), (ymin, ymax), (zmin, zmax)).

        For a rotated panel this is the AABB of the rotated box (a conservative
        over-approximation in X/Y); Z is unaffected by a Z-rotation.
        """
        cx, cy, cz = self.center
        sx, sy, sz = self.size
        if not self.is_rotated:
            hx, hy = sx / 2, sy / 2
        else:
            a = math.radians(self.rot_z)
            ca, sa = abs(math.cos(a)), abs(math.sin(a))
            hx = sx / 2 * ca + sy / 2 * sa
            hy = sx / 2 * sa + sy / 2 * ca
        return ((cx - hx, cx + hx), (cy - hy, cy + hy), (cz - sz / 2, cz + sz / 2))


@dataclass
class FrontItem:
    """One door / drawer / mullion / blind-filler in the front plane.

    Geometry uses the full placement (``x``/``y``/``z`` centre + ``width`` x
    ``thickness`` x ``height``); the cut list uses only the flat dimensions.
    Both read the same object so the 3D model and the parts list cannot drift.
    """

    kind: str            # "drawer" | "door" | "mullion" | "filler"
    width: float         # face width (X)
    height: float        # face height (Z)
    thickness: float     # stock thickness (Y)
    x: float             # X centre in the cabinet frame
    y: float             # Y centre (front-plane depth)
    z: float             # Z centre
    index: int = 0       # 1-based drawer index (drawers only)
    hand: str = ""       # "L" / "R" for a pair of doors, else ""
    false_front: bool = False


@dataclass
class FrontPlan:
    """The complete front layout shared by the compiler and the cut list."""

    opening_w: float        # clear opening after the face frame / blind return
    region_bottom: float    # Z of the bottom of the usable front region
    region_h: float         # height of that region
    is_face_frame: bool
    items: list[FrontItem]

    @property
    def drawers(self) -> list[FrontItem]:
        return [i for i in self.items if i.kind == "drawer"]

    @property
    def doors(self) -> list[FrontItem]:
        return [i for i in self.items if i.kind == "door"]

    @property
    def mullion(self) -> FrontItem | None:
        return next((i for i in self.items if i.kind == "mullion"), None)


def front_plan(spec: CabinetSpec) -> FrontPlan:
    """Lay out the fronts (doors, drawers, mullion, blind filler) for *spec*.

    Drawers stack from the top; doors fill what remains. This is the single
    source of truth for front sizing and placement — the compiler turns each
    item into a panel, the cut list into a part.
    """
    m = spec.material
    toe_h = spec.toe_kick_height
    box_h = spec.box_height
    is_ff = spec.construction == Construction.FACE_FRAME

    if is_ff:                                   # inset, flush with the frame
        opening_w = spec.width - 2 * FRAME_WIDTH
        region_bottom = toe_h + FRAME_WIDTH
        region_h = box_h - 2 * FRAME_WIDTH
        y_front = -FRAME_THICKNESS + m.door / 2
    else:                                       # overlay, proud of the carcass
        opening_w = spec.width
        region_bottom = toe_h
        region_h = box_h
        y_front = -m.door / 2

    items: list[FrontItem] = []

    # Blind corner: a fixed filler covers the blind return; the opening shifts.
    front_cx = 0.0
    if spec.cabinet_type == CabinetType.CORNER_BLIND and spec.blind_width > 0:
        bw = spec.blind_width
        opening_w -= bw
        front_cx = bw / 2
        filler_w = bw - spec.reveal
        items.append(FrontItem(
            "filler", filler_w, region_h - 2 * spec.reveal, m.door,
            x=-spec.width / 2 + spec.reveal + filler_w / 2, y=y_front,
            z=region_bottom + region_h / 2))

    # Drawers stack down from the top of the region.
    drawer_band = 0.0
    z_cursor = region_bottom + region_h
    for i, dr in enumerate(spec.drawers, start=1):
        fw = opening_w - 2 * spec.reveal
        z = z_cursor - spec.reveal - dr.front_height / 2
        items.append(FrontItem(
            "drawer", fw, dr.front_height, m.door,
            x=front_cx, y=y_front, z=z, index=i, false_front=dr.false_front))
        z_cursor -= dr.front_height + spec.reveal
        drawer_band += dr.front_height + spec.reveal

    # Doors fill the rest of the region.
    door_region = region_h - drawer_band
    if spec.doors > 0 and door_region > 0:
        door_h = door_region - 2 * spec.reveal
        z = region_bottom + door_region / 2
        mullion_w = (FRAME_WIDTH if is_ff else MULLION_WIDTH) \
            if (spec.center_mullion and spec.doors == 2) else 0.0
        if mullion_w:
            m_th = FRAME_THICKNESS if is_ff else m.door
            items.append(FrontItem(
                "mullion", mullion_w, door_region, m_th,
                x=front_cx, y=-m_th / 2, z=z))
        if spec.doors == 1:
            dw = opening_w - 2 * spec.reveal
            items.append(FrontItem(
                "door", dw, door_h, m.door, x=front_cx, y=y_front, z=z))
        else:
            if mullion_w:
                dw = (opening_w - mullion_w) / 2 - 2 * spec.reveal
                offset = mullion_w / 2 + spec.reveal + dw / 2
            else:
                dw = (opening_w - 3 * spec.reveal) / 2
                offset = spec.reveal / 2 + dw / 2
            items.append(FrontItem("door", dw, door_h, m.door,
                                   x=front_cx - offset, y=y_front, z=z, hand="L"))
            items.append(FrontItem("door", dw, door_h, m.door,
                                   x=front_cx + offset, y=y_front, z=z, hand="R"))

    return FrontPlan(opening_w, region_bottom, region_h, is_ff, items)


def project_layout(project: Project) -> list[PanelBox]:
    """Every panel of a whole run, placed in the shared (global) frame.

    Each component's local panels (X centred on the box, Y=0 at its front,
    Z=0 on the floor) are transformed into the run frame:

    * ``component.x`` is the run-X of the component's *left* edge, ``component.y``
      the run-Y of its front — so a straight run is just side-by-side offsets;
    * ``component.rotation`` (degrees, CCW about vertical) spins the component
      about the centre of its front edge, for an end return.

    Built from :func:`panel_layout`, so the assembled model the compiler builds
    and the Critic measures is exactly the sum of the per-component layouts.
    """
    out: list[PanelBox] = []
    for i, comp in enumerate(project.components, start=1):
        tag = comp.label or getattr(comp.spec, "name", "") or f"C{i}"
        w = float(getattr(comp.spec, "width", 0.0) or 0.0)
        dx = comp.x + w / 2.0          # left-edge anchor -> component centre
        ca = math.cos(math.radians(comp.rotation))
        sa = math.sin(math.radians(comp.rotation))
        for p in panel_layout(comp.spec):
            cx, cy, cz = p.center
            wx = cx * ca - cy * sa + dx
            wy = cx * sa + cy * ca + comp.y
            out.append(PanelBox(
                label=f"{tag} · {p.label}", size=p.size, center=(wx, wy, cz),
                category=p.category, rot_z=p.rot_z + comp.rotation,
                oversized=p.oversized))
    return out


def panel_layout(spec) -> list[PanelBox]:
    """Return every panel of *spec* placed in the shared coordinate frame."""
    if isinstance(spec, Project):
        return project_layout(spec)
    if isinstance(spec, TableSpec):
        return _table_layout(spec)
    if spec.cabinet_type == CabinetType.CORNER_DIAGONAL:
        return _diagonal_layout(spec)

    m = spec.material
    toe_h = spec.toe_kick_height
    box_h = spec.box_height
    interior_w = spec.interior_width
    interior_d = spec.interior_depth
    # A captured back sits inside the carcass, so the rear rail is set forward of
    # it; an applied back lays on the outside rear face and needs no inset.
    back_inset = 0.0 if spec.back == BackStyle.APPLIED else m.back

    panels: list[PanelBox] = []

    def add(label, size, center, category="carcass", rot_z=0.0):
        panels.append(PanelBox(label, size, center, category, rot_z))

    z_box = toe_h + box_h / 2
    y_center = spec.depth / 2

    # --- sides -----------------------------------------------------------
    x_side = spec.width / 2 - m.carcass / 2
    add("Side L", (m.carcass, spec.depth, box_h), (-x_side, y_center, z_box))
    add("Side R", (m.carcass, spec.depth, box_h), (x_side, y_center, z_box))

    # --- bottom ----------------------------------------------------------
    add("Bottom", (interior_w, interior_d, m.carcass),
        (0, interior_d / 2, toe_h + m.carcass / 2))

    # --- top: a full panel (wall/tall) or two rails (base) ---------------
    z_top = toe_h + box_h - m.carcass / 2
    if spec.has_full_top:
        add("Top", (interior_w, interior_d, m.carcass),
            (0, interior_d / 2, z_top))
    else:
        add("Stretcher front", (interior_w, STRETCHER_WIDTH, m.carcass),
            (0, STRETCHER_WIDTH / 2, z_top))
        add("Stretcher back", (interior_w, STRETCHER_WIDTH, m.carcass),
            (0, spec.depth - back_inset - STRETCHER_WIDTH / 2, z_top))

    # --- back ------------------------------------------------------------
    if spec.back == BackStyle.APPLIED:
        # Lays on the rear face, adding its thickness behind the carcass.
        add("Back", (spec.width, m.back, box_h),
            (0, spec.depth + m.back / 2, z_box), category="back")
    else:  # captured between the sides, in front of the rear edge
        add("Back", (interior_w, m.back, box_h - m.carcass),
            (0, spec.depth - m.back / 2, z_box), category="back")

    # --- shelves (evenly distributed in the interior) --------------------
    if spec.shelves > 0:
        shelf_w = interior_w - 2 * SHELF_SIDE_CLEARANCE
        shelf_d = interior_d - SHELF_SETBACK
        usable = box_h - 2 * m.carcass
        for i in range(spec.shelves):
            frac = (i + 1) / (spec.shelves + 1)
            z = toe_h + m.carcass + frac * usable
            add(f"Shelf {i + 1}", (shelf_w, shelf_d, m.shelf),
                (0, shelf_d / 2 + m.back, z), category="shelf")

    # --- toe kick --------------------------------------------------------
    if spec.toe_kick and toe_h > 0:
        setback = spec.toe_kick.setback
        add("Toe kick", (spec.width, m.carcass, toe_h),
            (0, setback + m.carcass / 2, toe_h / 2), category="toe")

    # --- face frame (stiles + rails) for face-frame construction ---------
    is_ff = spec.construction == Construction.FACE_FRAME
    if is_ff:
        y_frame = -FRAME_THICKNESS / 2
        x_stile = spec.width / 2 - FRAME_WIDTH / 2
        add("Stile L", (FRAME_WIDTH, FRAME_THICKNESS, box_h),
            (-x_stile, y_frame, z_box), category="frame")
        add("Stile R", (FRAME_WIDTH, FRAME_THICKNESS, box_h),
            (x_stile, y_frame, z_box), category="frame")
        rail_w = spec.width - 2 * FRAME_WIDTH
        add("Rail top", (rail_w, FRAME_THICKNESS, FRAME_WIDTH),
            (0, y_frame, toe_h + box_h - FRAME_WIDTH / 2), category="frame")
        add("Rail bottom", (rail_w, FRAME_THICKNESS, FRAME_WIDTH),
            (0, y_frame, toe_h + FRAME_WIDTH / 2), category="frame")

    # --- fronts: doors, drawers, mullion, blind filler (shared layout) ---
    # The same plan the cut list consumes, so panels and parts never disagree.
    for it in front_plan(spec).items:
        if it.kind == "mullion":
            label, category = ("Center stile" if is_ff else "Mullion"), "frame"
        elif it.kind == "drawer":
            label, category = f"Drawer front {it.index}", "front"
        elif it.kind == "filler":
            label, category = "Blind filler", "front"
        else:  # door
            label, category = ("Door" if not it.hand else f"Door {it.hand}"), "front"
        add(label, (it.width, it.thickness, it.height), (it.x, it.y, it.z),
            category=category)

    return panels


def _diagonal_layout(spec: CabinetSpec) -> list[PanelBox]:
    """A diagonal (angled-front) corner cabinet.

    Footprint is W x D with the front-right corner cut by a 45° chamfer of leg
    ``corner_cut``; an angled door (a Z-rotated panel) closes that chamfer. The
    left side and back run full; the right side and front rail are shortened to
    leave the chamfer open.
    """
    m = spec.material
    W, D = spec.width, spec.depth
    t = m.carcass
    c = spec.corner_cut
    toe_h = spec.toe_kick_height
    box_h = spec.box_height
    z_box = toe_h + box_h / 2

    panels: list[PanelBox] = []

    def add(label, size, center, category="carcass", rot_z=0.0, oversized=False):
        panels.append(PanelBox(label, size, center, category, rot_z, oversized))

    # Carcass shell (outer faces sit on the footprint extremes).
    add("Side L", (t, D, box_h), (-W / 2 + t / 2, D / 2, z_box))
    add("Side R", (t, D - c, box_h), (W / 2 - t / 2, (c + D) / 2, z_box))
    add("Back", (W - 2 * t, t, box_h), (0, D - t / 2, z_box), category="back")
    # Front rail runs from the left side to where the chamfer begins.
    front_w = (W / 2 - c) - (-W / 2 + t)
    add("Front rail", (front_w, t, box_h),
        ((-W / 2 + t + W / 2 - c) / 2, t / 2, z_box))

    # Bottom and top blanks: square stock trimmed to the pentagon on site.
    add("Bottom", (W - 2 * t, D - 2 * t, t), (0, D / 2, toe_h + t / 2),
        category="carcass", oversized=True)
    add("Top", (W - 2 * t, D - 2 * t, t), (0, D / 2, toe_h + box_h - t / 2),
        category="carcass", oversized=True)

    # Toe kick along the front.
    if spec.toe_kick and toe_h > 0:
        add("Toe kick", (W, t, toe_h),
            (0, spec.toe_kick.setback + t / 2, toe_h / 2), category="toe")

    # Shelves (rectangular blanks; trimmed to the corner in the shop).
    if spec.shelves > 0:
        usable = box_h - 2 * t
        for i in range(spec.shelves):
            frac = (i + 1) / (spec.shelves + 1)
            add(f"Shelf {i + 1}", (W - 2 * t - 4, D - 2 * t - 4, m.shelf),
                (0, D / 2, toe_h + t + frac * usable), category="shelf",
                oversized=True)

    # The angled door across the chamfer, from (W/2-c, 0) to (W/2, c).
    door_len = max(c * math.sqrt(2) - 2 * spec.reveal, 50.0)
    door_h = box_h - 2 * spec.reveal
    mid = (W / 2 - c / 2, c / 2)
    # Nudge the door outward (front-right) along the chamfer normal.
    nx, ny = (1 / math.sqrt(2), -1 / math.sqrt(2))
    cx = mid[0] + nx * m.door / 2
    cy = mid[1] + ny * m.door / 2
    add("Door", (door_len, m.door, door_h), (cx, cy, z_box),
        category="front", rot_z=45.0)

    return panels


def _table_layout(spec: TableSpec) -> list[PanelBox]:
    """A four-legged table: a top, four legs, and four aprons."""
    W, D, H = spec.width, spec.depth, spec.height
    tt, leg, ah, at, li = (spec.top_thickness, spec.leg, spec.apron_height,
                           spec.apron_thickness, spec.leg_inset)
    panels: list[PanelBox] = []

    def add(label, size, center, category):
        panels.append(PanelBox(label, size, center, category))

    add("Top", (W, D, tt), (0, 0, H - tt / 2), "top")

    leg_h = H - tt
    lx = W / 2 - li - leg / 2          # leg-centre offsets
    ly = D / 2 - li - leg / 2
    for i, sx in enumerate((-1, 1)):
        for j, sy in enumerate((-1, 1)):
            add(f"Leg {2 * i + j + 1}", (leg, leg, leg_h),
                (sx * lx, sy * ly, leg_h / 2), "leg")

    az = H - tt - ah / 2               # apron centre height
    apron_x = 2 * lx - leg             # long apron length (between legs, X)
    apron_y = 2 * ly - leg             # short apron length (between legs, Y)
    for sy in (-1, 1):
        add("Apron long", (apron_x, at, ah), (0, sy * ly, az), "apron")
    for sx in (-1, 1):
        add("Apron short", (at, apron_y, ah), (sx * lx, 0, az), "apron")

    return panels
