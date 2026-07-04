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
from enum import Enum

from .dsl import (
    CabinetSpec, TableSpec, ComponentGroup, Component, BackStyle,
    Construction, CabinetType, leg_section,
)
from .dispatch import spec_kind, is_group, VOID, GROUP, TABLE, CABINET
from . import furniture

# Construction constants shared with the cut list (neutral module, no cycle).
from .constants import (
    STRETCHER_WIDTH, SHELF_SIDE_CLEARANCE, SHELF_SETBACK,
    FRAME_WIDTH, FRAME_THICKNESS, MULLION_WIDTH,
    DOOR_STILE_WIDTH, DOOR_RAIL_WIDTH, MIN_DRAWER_BOX_WIDTH_3D,
    HOUSED_DEPTH_FRACTION,
)
from .partmath import drawer_box_dims, door_panel_dims


class PanelRole(Enum):
    """What a placed panel *is*, for stages that act on panel identity.

    Decoded once from the panel label convention (see :func:`classify_panel_role`)
    so a consumer like the drilling schedule dispatches on a typed role instead of
    re-deriving it from ``label.startswith("Side")`` string tests. ``SIDE_LEFT`` /
    ``SIDE_RIGHT`` carry the hand the boring needs; everything unrecognised is
    ``OTHER``.
    """

    SIDE_LEFT = "side_left"
    SIDE_RIGHT = "side_right"
    DOOR = "door"
    DRAWER_FRONT = "drawer_front"
    OTHER = "other"


def classify_panel_role(label: str) -> PanelRole:
    """Map a panel label to its :class:`PanelRole` — the one place the label
    convention is decoded.

    Mirrors exactly the matches the drilling schedule used to open-code: any
    ``Side*`` panel is a side (right when the label ends in ``R``, else left); a
    ``Door``/``Door L``/``Door R`` is a door; a ``Drawer front N`` is a drawer
    front. Keep this in sync with the labels the layout functions emit.
    """
    if label.startswith("Side"):
        return PanelRole.SIDE_RIGHT if label.endswith("R") else PanelRole.SIDE_LEFT
    if label == "Door" or label.startswith("Door "):
        return PanelRole.DOOR
    if label.startswith("Drawer front"):
        return PanelRole.DRAWER_FRONT
    return PanelRole.OTHER


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
    subassembly: str = ""       # which buildable unit this panel belongs to
    # Rectangular openings cut through this panel, each ``(cx, cy, w, d)`` — the
    # opening centre relative to the panel centre (mm) plus its size in X/Y. Used
    # for a countertop's sink/cooktop cut-out; the compiler subtracts a box (only
    # when build123d is present, so a CAD-free run is unaffected).
    openings: tuple = ()
    # Which face is the assembly *interior*, along the panel's thickness (normal)
    # axis: +1 = the +normal face (the default — e.g. a left side, whose inner
    # face points +X), -1 = the -normal face (a right-hand panel — a right side or
    # a right drawer-box wall — whose inner face points -X). Housings (dados/
    # grooves/back rabbets) and bores are cut from this inner face, so a mirrored
    # panel gets its groove on the correct side instead of the outside.
    inner_sign: float = 1.0
    # Half-extension (per axis, mm) by which this panel is grown to SEAT INTO the
    # dado/groove that houses it (so a captured bottom/top/shelf reaches into its
    # slot instead of floating short). The structural interference check subtracts
    # this back out, because seating into a housing is a joint, not a collision.
    capture_grow: tuple = (0.0, 0.0, 0.0)

    @property
    def role(self) -> "PanelRole":
        """The panel's identity (side/door/drawer-front/other), typed.

        Derived from the label convention in one place so drilling and any other
        identity-driven stage dispatch on the enum, not on string prefixes.
        """
        return classify_panel_role(self.label)

    @property
    def is_front(self) -> bool:
        return self.category == "front"

    @property
    def unit(self) -> str:
        """The sub-assembly this panel belongs to ('Carcass' by default)."""
        return self.subassembly or "Carcass"

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


def component_tag(comp: Component, index: int = 1) -> str:
    """Short label for a component: its explicit label, else its name, else Cn."""
    return comp.label or getattr(comp.spec, "name", "") or f"C{index}"


def _placement(comp: Component):
    """Transform fn local (x, y) -> world (x, y) for a placed component.

    A leaf component is anchored by its **front-left corner** (local
    (-width/2, 0)): ``component.x``/``component.y`` are where that corner sits in
    the run, and ``component.rotation`` (degrees, CCW about vertical) turns the
    component about it. So a straight run is side-by-side offsets, and turning a
    run 90° at a corner just rotates each piece about the corner it butts to.

    A nested **sub-assembly** (group) has no single width to anchor by; its child
    panels are already placed in the group's own local frame, so it is anchored
    at its local origin (0, 0) and ``x``/``y``/``rotation`` translate and rotate
    that whole frame.
    """
    grp = is_group(comp.spec)
    w = 0.0 if grp else float(getattr(comp.spec, "width", 0.0) or 0.0)
    a = math.radians(comp.rotation)
    ca, sa = math.cos(a), math.sin(a)

    def place(lx: float, ly: float) -> tuple[float, float]:
        # Re-anchor from the box centre (local X=0) to the front-left corner.
        rx, ry = lx + w / 2.0, ly
        return (rx * ca - ry * sa + comp.x, rx * sa + ry * ca + comp.y)

    return place


def local_plan_bounds(spec) -> tuple[float, float, float, float]:
    """The spec's plan extent in its own local frame (xmin, xmax, ymin, ymax).

    A leaf cabinet/table is a ``width`` × ``depth`` rectangle centred on X with
    its front at Y=0. A sub-assembly's plan box is the union of its placed
    panels' footprints, so a placed group is overlap-checked by its real outline
    rather than a missing ``width``.
    """
    if is_group(spec):
        xs: list[float] = []
        ys: list[float] = []
        for p in project_layout(spec):
            (x0, x1), (y0, y1), _ = p.bounds()
            xs += [x0, x1]
            ys += [y0, y1]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), max(xs), min(ys), max(ys))
    w = float(getattr(spec, "width", 0.0) or 0.0)
    d = float(getattr(spec, "depth", 0.0) or 0.0)
    return (-w / 2, w / 2, 0.0, d)


def footprint_corners(comp: Component) -> list[tuple[float, float]]:
    """The component's plan rectangle in the run frame (4 world (x, y) points)."""
    place = _placement(comp)
    xmin, xmax, ymin, ymax = local_plan_bounds(comp.spec)
    return [place(xmin, ymin), place(xmax, ymin),
            place(xmax, ymax), place(xmin, ymax)]


def _project_poly(poly, ax: float, ay: float) -> tuple[float, float]:
    ds = [x * ax + y * ay for (x, y) in poly]
    return min(ds), max(ds)


def footprints_overlap(a: Component, b: Component, slack: float = 1.0) -> bool:
    """True if two components' plan footprints overlap (oriented, SAT).

    Works for any rotation, so it catches the inner-corner collision where two
    perpendicular runs meet. ``slack`` (mm) lets neighbours that merely butt
    pass; only real interpenetration counts.
    """
    pa, pb = footprint_corners(a), footprint_corners(b)
    for poly in (pa, pb):                       # each rectangle's two edge axes
        for i in (1, 3):
            ex, ey = poly[i][0] - poly[0][0], poly[i][1] - poly[0][1]
            n = math.hypot(ex, ey)
            if n == 0:
                continue
            ax, ay = ex / n, ey / n
            amin, amax = _project_poly(pa, ax, ay)
            bmin, bmax = _project_poly(pb, ax, ay)
            if amin > bmax - slack or bmin > amax - slack:
                return False                    # a separating axis -> disjoint
    return True


def project_layout(project: ComponentGroup) -> list[PanelBox]:
    """Every panel of a whole group, placed in the group's (global) frame.

    Each component's local panels (X centred on the box, Y=0 at its front,
    Z=0 on the floor) are transformed into the group frame by :func:`_placement`
    (front-left-corner anchor + rotation), so L- and U-shaped runs assemble
    correctly. A component whose spec is itself a sub-assembly contributes its
    own placed panels, transformed again by this component's placement — nesting
    composes by construction. Built from :func:`panel_layout`, so the model the
    compiler builds and the Critic measures is exactly the sum of the
    per-component layouts.
    """
    out: list[PanelBox] = []
    for i, comp in enumerate(project.components, start=1):
        tag = component_tag(comp, i)
        place = _placement(comp)
        for p in panel_layout(comp.spec):
            cx, cy, cz = p.center
            wx, wy = place(cx, cy)
            out.append(PanelBox(
                label=f"{tag} · {p.label}", size=p.size, center=(wx, wy, cz),
                category=p.category, rot_z=p.rot_z + comp.rotation,
                oversized=p.oversized, subassembly=tag,
                openings=p.openings,
                # Carry the machining hints through so a mirrored side in a run
                # still cuts its groove on the inside and a captured bottom still
                # seats in its dado (else every project loses these).
                inner_sign=p.inner_sign, capture_grow=p.capture_grow))
    out += _run_countertop_panels(project)
    return out


def _is_under_counter(spec) -> bool:
    """A base cabinet a continuous worktop sits over (mirrors the cut list)."""
    if spec_kind(spec) == CABINET:
        ct = getattr(spec, "cabinet_type", None)
        return str(getattr(ct, "value", ct)).lower() == "base"
    return False


def _run_countertop_panels(project) -> list[PanelBox]:
    """One continuous worktop slab spanning the run's base cabinets, as a real
    body — the geometry counterpart of the cut list's ``_add_run_countertop``.

    Sized and placed from the true world-space footprint of the under-counter
    components (via :func:`footprint_corners`), so it is correct for a straight
    run, an L-run, or a back-to-back island. ``depth`` may be overridden to force
    an exact slab (e.g. an island worktop flush to the footprint). Emitted in the
    ``counter`` category so it never distorts the carcass envelope the Critic
    measures, and as its own ``Worktop`` subassembly so it is one Fusion body."""
    spec_ct = getattr(project, "countertop", None)
    if not isinstance(spec_ct, dict):
        return []
    unders = [c for c in project.components if _is_under_counter(c.spec)]
    if not unders:
        return []
    xs: list[float] = []
    ys: list[float] = []
    tops: list[float] = []
    for comp in unders:
        for (px, py) in footprint_corners(comp):
            xs.append(px)
            ys.append(py)
        s = comp.spec
        tops.append(float(getattr(s, "toe_kick_height", 0.0))
                    + float(getattr(s, "box_height", 0.0)))
    left, right = min(xs), max(xs)
    front, back = min(ys), max(ys)
    ct = float(spec_ct.get("thickness") or 38.0)
    overhang = float(spec_ct.get("overhang") or 25.0)
    depth = float(spec_ct.get("depth") or 0.0) or round((back - front) + overhang, 1)
    z_top = max(tops)
    return [PanelBox(
        "Run countertop", (round(right - left, 1), round(depth, 1), ct),
        ((left + right) / 2.0, (front + back) / 2.0, z_top + ct / 2.0),
        "counter", subassembly="Worktop")]


def panel_layout(spec) -> list[PanelBox]:
    """Return every panel of *spec* placed in the shared coordinate frame.

    VOID/GROUP are handled here (a gap builds nothing; a group composes its
    components); every *leaf* type dispatches through the
    :mod:`furniture` registry, so a new furniture type adds its panels by
    registering, not by editing this function.
    """
    kind = spec_kind(spec)
    if kind == VOID:
        return []                      # a reserved gap builds no carcass
    if kind == GROUP:
        return project_layout(spec)
    return furniture.get(kind).panels(spec)


def _cabinet_layout(spec) -> list[PanelBox]:
    """Panel placement for a cabinet (every CabinetType variant)."""
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

    def add(label, size, center, category="carcass", rot_z=0.0, unit="Carcass",
            inner_sign=1.0, capture_grow=(0.0, 0.0, 0.0)):
        panels.append(PanelBox(label, size, center, category, rot_z,
                               subassembly=unit, inner_sign=inner_sign,
                               capture_grow=capture_grow))

    z_box = toe_h + box_h / 2
    y_center = spec.depth / 2

    # A dado/rabbet houses the bottom/top in a slot in the sides, so those panels
    # run WIDER than the clear interior — into both slots. A butt/screw/dowel/
    # domino carcass has no such slot, so they stay clear-interior.
    grow = (m.carcass * HOUSED_DEPTH_FRACTION
            if str(spec.joinery).lower() in ("dado", "rabbet") else 0.0)

    # --- sides -----------------------------------------------------------
    # The right side is a mirror of the left: its interior face points -X, so its
    # housings (back groove, shelf dados) and bores are cut from the -normal face.
    x_side = spec.width / 2 - m.carcass / 2
    add("Side L", (m.carcass, spec.depth, box_h), (-x_side, y_center, z_box))
    add("Side R", (m.carcass, spec.depth, box_h), (x_side, y_center, z_box),
        inner_sign=-1.0)

    # --- bottom ----------------------------------------------------------
    add("Bottom", (interior_w + 2 * grow, interior_d, m.carcass),
        (0, interior_d / 2, toe_h + m.carcass / 2),
        capture_grow=(grow, 0.0, 0.0))

    # --- top: a full panel (wall/tall) or two rails (base) ---------------
    z_top = toe_h + box_h - m.carcass / 2
    if spec.has_full_top:
        add("Top", (interior_w + 2 * grow, interior_d, m.carcass),
            (0, interior_d / 2, z_top), capture_grow=(grow, 0.0, 0.0))
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
            (-x_stile, y_frame, z_box), category="frame", unit="Face frame")
        add("Stile R", (FRAME_WIDTH, FRAME_THICKNESS, box_h),
            (x_stile, y_frame, z_box), category="frame", unit="Face frame")
        rail_w = spec.width - 2 * FRAME_WIDTH
        add("Rail top", (rail_w, FRAME_THICKNESS, FRAME_WIDTH),
            (0, y_frame, toe_h + box_h - FRAME_WIDTH / 2), category="frame",
            unit="Face frame")
        add("Rail bottom", (rail_w, FRAME_THICKNESS, FRAME_WIDTH),
            (0, y_frame, toe_h + FRAME_WIDTH / 2), category="frame",
            unit="Face frame")

    # --- fronts: doors, drawers, mullion, blind filler (shared layout) ---
    # The same plan the cut list consumes, so panels and parts never disagree.
    plan = front_plan(spec)
    for it in plan.items:
        if it.kind == "door":
            # Slab or 5-piece (stile-and-rail) depending on door_style.
            panels.extend(_door_panels(it, spec))
            continue
        if it.kind == "mullion":
            label, category, unit = (
                "Center stile" if is_ff else "Mullion"), "frame", "Face frame"
            add(label, (it.width, it.thickness, it.height), (it.x, it.y, it.z),
                category=category, unit=unit)
        elif it.kind == "drawer":
            unit = f"Drawer {it.index}"
            add(f"Drawer front {it.index}", (it.width, it.thickness, it.height),
                (it.x, it.y, it.z), category="front", unit=unit)
            if not it.false_front:
                panels.extend(_drawer_box_panels(it, spec, plan))
        else:  # blind filler
            add("Blind filler", (it.width, it.thickness, it.height),
                (it.x, it.y, it.z), category="front", unit="Carcass")

    # --- accessories: countertop, filler, end panel, molding -------------
    panels.extend(_accessory_panels(spec))

    return panels


def _digits(s: str, default: int = 0) -> int:
    """Integer formed from every digit in *s* (``"Drawer 2 box"`` -> 2).

    One definition of the index-from-label idiom that used to be hand-inlined
    in several places. Returns *default* when *s* has no digits.
    """
    d = "".join(c for c in s if c.isdigit())
    return int(d) if d else default


def trailing_index(s: str, default: int = 0) -> int:
    """The trailing integer token of *s* (``"Drawer front 1"`` -> 1).

    The shared "instance from a placement label" idiom: returns *default* when
    the last whitespace-separated token isn't a plain integer (e.g. "Side L").
    """
    last = s.rsplit(" ", 1)[-1] if s else ""
    return int(last) if last.isdigit() else default


def _unit_sort_key(name: str) -> tuple:
    """Canonical build order for sub-assemblies (Carcass first, trim last)."""
    n = name.lower()
    if n == "carcass":
        return (0, 0, name)
    if n == "face frame":
        return (1, 0, name)
    if n.startswith("drawer"):
        return (2, _digits(n), name)
    if n.startswith("door"):
        return (3, 0, name)
    if n == "countertop":
        return (4, 0, name)
    if n == "trim":
        return (5, 0, name)
    return (6, 0, name)   # project cabinets / anything else


def subassembly_order(panels: list[PanelBox]) -> list[str]:
    """Distinct sub-assembly names in *panels*, in canonical build order."""
    return sorted({p.unit for p in panels}, key=_unit_sort_key)


def panels_by_subassembly(spec) -> dict:
    """``{sub-assembly name: [panels]}`` for *spec*, in build order."""
    panels = panel_layout(spec)
    groups: dict[str, list[PanelBox]] = {}
    for p in panels:
        groups.setdefault(p.unit, []).append(p)
    return {name: groups[name] for name in subassembly_order(panels)}


def _explode_offset(p: PanelBox, dims: tuple[float, float, float],
                    factor: float) -> tuple[float, float, float]:
    """How far to move panel *p* in an exploded view (mm), scaled by *factor*."""
    W, D, H = dims
    u, cat, f = p.unit, p.category, factor
    if cat == "back":
        return (0.0, D * 0.7 * f, 0.0)            # back lifts off rearward
    if u == "Face frame":
        return (0.0, -D * 0.5 * f, 0.0)           # face frame floats forward
    if u.startswith("Door"):
        hx = -W * 0.4 * f if u.endswith(" L") else (
            W * 0.4 * f if u.endswith(" R") else -W * 0.25 * f)
        return (hx, -D * 0.95 * f, 0.0)           # doors swing off the front
    if u.startswith("Drawer"):
        i = _digits(u, 1)
        return (0.0, -D * (0.45 + 0.4 * i) * f, 0.0)   # drawers pull forward
    if cat == "shelf":
        i = _digits(p.label, 1)
        return (0.0, -D * 0.2 * f, H * 0.18 * i * f)   # shelves lift + forward
    if cat == "toe":
        return (0.0, -D * 0.2 * f, -H * 0.3 * f)
    if u == "Countertop":
        return (0.0, 0.0, H * 0.45 * f)
    if u == "Trim":
        sx = 1.0 if p.center[0] >= 0 else -1.0
        return (sx * W * 0.45 * f, 0.0, H * 0.15 * f)
    return (0.0, 0.0, 0.0)                         # carcass stays put


def explode_panels(spec, factor: float = 1.0,
                   include: set | None = None) -> list[PanelBox]:
    """Panels of *spec* offset by sub-assembly to show how it goes together.

    ``factor`` 0 = assembled, 1 = fully separated. ``include`` optionally keeps
    only the named sub-assemblies (for a progressive build view). Each cabinet
    of a project explodes within its own placement.
    """
    panels = panel_layout(spec)
    if include is not None:
        panels = [p for p in panels if p.unit in include]
    W = float(getattr(spec, "width", 0.0) or 0.0)
    D = float(getattr(spec, "depth", 0.0) or 0.0)
    H = float(getattr(spec, "height", 0.0) or 0.0)
    if not (W and D and H):   # tables / groups: fall back to the panel bounds
        xs = [b for p in panels for b in p.bounds()[0]]
        ys = [b for p in panels for b in p.bounds()[1]]
        zs = [b for p in panels for b in p.bounds()[2]]
        W = (max(xs) - min(xs)) if xs else 600.0
        D = (max(ys) - min(ys)) if ys else 560.0
        H = (max(zs) - min(zs)) if zs else 720.0
    dims = (W, D, H)
    out: list[PanelBox] = []
    for p in panels:
        ox, oy, oz = _explode_offset(p, dims, factor)
        cx, cy, cz = p.center
        out.append(PanelBox(p.label, p.size, (cx + ox, cy + oy, cz + oz),
                            p.category, p.rot_z, p.oversized, p.subassembly,
                            p.openings))
    return out


def _door_panels(it: "FrontItem", spec: CabinetSpec) -> list[PanelBox]:
    """Panels for one door leaf — a single slab, or a 5-piece frame + panel.

    For a non-slab ``door_style`` the leaf becomes two stiles, two rails and a
    recessed centre panel. The hinge-side stile keeps the leaf's ``Door``/``Door
    L``/``Door R`` label so the drilling schedule still bores the hinge cup into
    it; the other parts take non-colliding labels. The five parts tile the leaf
    (touching, not overlapping), so the Critic's coverage and interference
    checks are unaffected.
    """
    label = "Door" if not it.hand else f"Door {it.hand}"
    unit = label                         # the door leaf is its own sub-assembly
    style = str(getattr(spec, "door_style", "slab")).lower()
    if style == "slab":
        return [PanelBox(label, (it.width, it.thickness, it.height),
                         (it.x, it.y, it.z), "front", subassembly=unit)]

    w, h, t = it.width, it.height, it.thickness
    pt = getattr(spec.material, "door_panel", 6.0)
    stile, rail = DOOR_STILE_WIDTH, DOOR_RAIL_WIDTH
    suf = f" {it.hand}" if it.hand else ""
    hinge_left = it.hand != "R"          # L door / single door hinge on the left
    sign = -1.0 if hinge_left else 1.0
    edge = w / 2 - stile / 2
    # The model tiles the *visible* frame opening (parts touch, never overlap) —
    # the same opening the cut list extends by the groove tongue. One source.
    dims = door_panel_dims(w, h)
    inner_w = max(dims.opening_w, 10.0)
    inner_h = max(dims.opening_h, 10.0)
    # Centre panel recessed: thinner stock, set flush to the frame's back face.
    panel_y = it.y + t / 2 - pt / 2

    def db(lbl, size, center):
        return PanelBox(lbl, size, center, "front", subassembly=unit)

    return [
        db(label, (stile, t, h), (it.x + sign * edge, it.y, it.z)),
        db(f"Stile{suf} latch", (stile, t, h), (it.x - sign * edge, it.y, it.z)),
        db(f"Rail{suf} top", (inner_w, t, rail),
           (it.x, it.y, it.z + h / 2 - rail / 2)),
        db(f"Rail{suf} bottom", (inner_w, t, rail),
           (it.x, it.y, it.z - h / 2 + rail / 2)),
        db(f"Panel{suf}", (inner_w, pt, inner_h), (it.x, panel_y, it.z)),
    ]


def _drawer_box_panels(it: "FrontItem", spec: CabinetSpec, plan) -> list[PanelBox]:
    """The four box walls + bottom of one drawer, placed behind its front.

    Sized like the cut list (opening less slide clearance, dropped below the
    front, set back from the interior), so the 3D model shows the real box that
    rides on the slides. Tagged to the ``Drawer N`` sub-assembly.
    """
    m = spec.material
    t = m.drawer_box
    unit = f"Drawer {it.index}"
    box_w, box_h, box_d = drawer_box_dims(
        plan.opening_w, it.height, spec.interior_depth,
        width_floor=MIN_DRAWER_BOX_WIDTH_3D)
    cx = it.x
    cy = box_d / 2 + 8.0          # just behind the drawer front
    cz = it.z                     # aligned with the front's centre height

    def db(lbl, size, center, inner_sign=1.0):
        return PanelBox(lbl, size, center, "drawer_box", subassembly=unit,
                        inner_sign=inner_sign)

    # The bottom is captured in a groove plowed in the two box sides (depth =
    # drawer_box × HOUSED_DEPTH_FRACTION per side), so it runs WIDER than the
    # clear interior — into both grooves — otherwise it floats short of them.
    groove_depth = t * HOUSED_DEPTH_FRACTION
    bottom_w = box_w - 2 * t + 2 * groove_depth      # into the side grooves
    return [
        db(f"Drawer {it.index} box side L", (t, box_d, box_h),
           (cx - box_w / 2 + t / 2, cy, cz)),
        # The right box wall is a mirror: its interior face points -X, so its
        # bottom groove is cut from the -normal face (not the outside).
        db(f"Drawer {it.index} box side R", (t, box_d, box_h),
           (cx + box_w / 2 - t / 2, cy, cz), inner_sign=-1.0),
        db(f"Drawer {it.index} box front", (box_w - 2 * t, t, box_h),
           (cx, cy - box_d / 2 + t / 2, cz)),
        db(f"Drawer {it.index} box back", (box_w - 2 * t, t, box_h),
           (cx, cy + box_d / 2 - t / 2, cz)),
        db(f"Drawer {it.index} box bottom", (bottom_w, box_d - 2 * t, m.back),
           (cx, cy, cz - box_h / 2 + m.back / 2)),
    ]


def _accessory_panels(spec: CabinetSpec) -> list[PanelBox]:
    """Geometry for the accessories on *spec*: countertop, filler, end panel,
    molding. Each sits just outside/above the carcass (touching, not
    overlapping), with its own category so it never distorts the carcass
    envelope the Critic measures.
    """
    out: list[PanelBox] = []
    m = spec.material
    box_top = spec.toe_kick_height + spec.box_height
    for a in getattr(spec, "accessories", None) or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind", "")).lower()
        if kind == "countertop":
            ct = float(a.get("thickness", 38.0))
            overhang = float(a.get("overhang", 25.0))
            total_d = spec.depth + overhang
            # Sink/cooktop cut-outs, mapped from the cut-list blank frame
            # (length=spec.width, width=depth+overhang, front-left origin) to
            # offsets from the counter panel's centre, so the compiler can
            # subtract a box for each.
            from .accessories import countertop_cutouts
            blank_w = float(a.get("depth", spec.depth + 25.0)) + overhang
            openings = tuple(
                (cx + cw / 2 - spec.width / 2,
                 cy + cd / 2 - blank_w / 2, cw, cd)
                for (cx, cy, cw, cd) in countertop_cutouts(spec))
            out.append(PanelBox(
                "Countertop", (spec.width + 2 * overhang, total_d, ct),
                (0.0, spec.depth / 2 - overhang / 2, box_top + ct / 2), "counter",
                subassembly="Countertop", openings=openings))
        elif kind == "filler":
            fw = float(a.get("width", 75.0))
            right = str(a.get("side", "")).lower() == "right"
            sign = 1.0 if right else -1.0
            out.append(PanelBox(
                "Filler", (fw, spec.depth, spec.box_height),
                (sign * (spec.width / 2 + fw / 2), spec.depth / 2,
                 spec.toe_kick_height + spec.box_height / 2), "filler",
                subassembly="Trim"))
        elif kind == "end_panel":
            right = str(a.get("side", "")).lower() == "right"
            sign = 1.0 if right else -1.0
            out.append(PanelBox(
                "End panel", (m.door, spec.depth, spec.box_height),
                (sign * (spec.width / 2 + m.door / 2), spec.depth / 2,
                 spec.toe_kick_height + spec.box_height / 2), "endpanel",
                subassembly="Trim"))
        elif kind == "molding":
            mtype = str(a.get("type", "crown"))
            mh = float(a.get("height", 90.0 if mtype == "crown" else 40.0))
            out.append(PanelBox(
                f"{mtype.title()} molding", (spec.width, m.carcass, mh),
                (0.0, m.carcass / 2, box_top + mh / 2), "molding",
                subassembly="Trim"))
    return out


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
    tt, ah, at, li = (spec.top_thickness, spec.apron_height,
                      spec.apron_thickness, spec.leg_inset)
    # Leg cross-section: leg_x along X, leg_y along Y (wide face along depth when
    # leg_depth is set). Square legs collapse to leg_x == leg_y == leg.
    leg_x, leg_y = leg_section(spec)
    panels: list[PanelBox] = []

    def add(label, size, center, category):
        panels.append(PanelBox(label, size, center, category))

    add("Top", (W, D, tt), (0, 0, H - tt / 2), "top")

    leg_h = H - tt
    lx = W / 2 - li - leg_x / 2        # leg-centre offsets (per-axis section)
    ly = D / 2 - li - leg_y / 2
    for i, sx in enumerate((-1, 1)):
        for j, sy in enumerate((-1, 1)):
            add(f"Leg {2 * i + j + 1}", (leg_x, leg_y, leg_h),
                (sx * lx, sy * ly, leg_h / 2), "leg")

    az = H - tt - ah / 2               # apron centre height
    apron_x = 2 * lx - leg_x           # long apron length (between legs, X)
    apron_y = 2 * ly - leg_y           # short apron length (between legs, Y)
    for sy in (-1, 1):
        add("Apron long", (apron_x, at, ah), (0, sy * ly, az), "apron")
    for sx in (-1, 1):
        add("Apron short", (at, apron_y, ah), (sx * lx, 0, az), "apron")

    return panels


# Register the built-in leaf placements. New furniture types register their own
# ``panels`` the same way (in their home module), so ``panel_layout`` never
# grows another branch.
furniture.register(CABINET, panels=_cabinet_layout)
furniture.register(TABLE, panels=_table_layout)
