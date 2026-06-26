"""Leaf implementations for the home-shop furniture types (H1).

Each type here is a pure-math leaf furniture: a spec dataclass in :mod:`dsl`, a
:mod:`dispatch` kind, and the five stage callables registered into
:mod:`furniture`. Importing this module wires those registrations, so the
generic pipeline stages (geometry / cutlist / validator / joinery / assembly)
dispatch to them with no stage-body edits — the whole point of the H0 refactor.

Types:

* **wall_shelf** — one board fixed to the wall by a French cleat or brackets.
* **box / chest** — a six-board box (4 sides + bottom + lid) with a selectable
  corner joint reusing the drawer-box :class:`~dsl.CornerJoint` vocabulary.
* **bench / stool** — a seat on four legs joined by aprons and lower stretchers
  (a low table superset; the shared LeggedSpec base is a follow-up).
* **frame** — a picture / mirror frame: four mitered rails with a rabbet for the
  glazing, art/mirror, and backer.
* **bed** — a knock-down bed: a headboard and footboard joined by two side rails
  with bed-bolt / hook-plate hardware, carrying a deck of cross slats.
* **cutting_board** — a glued-up cutting / charcuterie board: N edge-glued
  strips (optionally two alternating species), edge/end/long grain.
* **nightstand** / **desk** — legged pieces (top + four legs + aprons) carrying
  apron-hung drawer(s) and a lower shelf / back modesty panel.
* **workbench** — a heavy bench: a thick laminated top on a leg-and-stretcher
  base, with bench-dog holes, a vise, and a tool shelf.

No CAD dependency.
"""

from __future__ import annotations

import math

from . import furniture
from .dispatch import (
    WALL_SHELF, BOX, BENCH, FRAME, BED, CUTTING_BOARD,
    NIGHTSTAND, DESK, WORKBENCH,
)
from .dsl import (
    WallShelfSpec, BoxSpec, BenchSpec, FrameSpec, BedSpec, CuttingBoardSpec,
    NightstandSpec, DeskSpec, WorkbenchSpec,
    ShelfFixing, FrameJoint, FrameHanger, FrameContents, BedConnector, GrainStyle,
)
from .geometry import PanelBox
from .partmath import drawer_box_dims
from .constants import MIN_DRAWER_BOX_WIDTH_3D
from .cutlist import CutList, Part, Hardware, assign_ids, resolve_part_stock
from .materials import (
    MAT_TOP, MAT_LEG, MAT_APRON, MAT_SOLID, MAT_SOLID_PANEL,
    MAT_DOOR_FRONT, MAT_DRAWER_BOX,
)
from .validator import Issue
from .joinery import JoineryOp
from .assembly_steps import SubAssembly, step
from . import engineering
from . import species
from . import hardware as hw


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _finite_positive(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


# ===========================================================================
# Wall shelf
# ===========================================================================

def _wall_shelf_panels(spec: WallShelfSpec) -> list[PanelBox]:
    """The shelf board plus its fixing, placed in the shared frame.

    X = length (centred on 0), Y = depth (0 at the front face, +Y toward the
    wall), Z = height (the shelf top sits at ``spec.height``). A French cleat
    contributes a wall strip (against the wall) and a shelf strip (under the
    board's rear); brackets contribute small blocks under the board.
    """
    L, D, t = spec.length, spec.depth, spec.thickness
    top_z = spec.mount_height               # where the board top hangs on the wall
    board_cz = top_z - t / 2
    panels: list[PanelBox] = [
        PanelBox("Shelf", (L, D, t), (0.0, D / 2, board_cz),
                 "shelf", subassembly="Shelf"),
    ]

    fixing = spec.fixing
    if fixing == ShelfFixing.FRENCH_CLEAT:
        ch = spec.cleat_height
        cz = board_cz - t / 2 - ch / 2          # hangs just under the board rear
        # The bevelled pair interlocks; model them as two abutting strips at the
        # rear (against the wall, +Y) so the positive-volume check sees no clash.
        panels.append(PanelBox(
            "Cleat (wall)", (L, t, ch), (0.0, D - t / 2, cz),
            "cleat", subassembly="Cleat"))
        panels.append(PanelBox(
            "Cleat (shelf)", (L, t, ch), (0.0, D - 3 * t / 2, cz),
            "cleat", subassembly="Cleat"))
    elif fixing == ShelfFixing.BRACKETS:
        n = max(spec.brackets, 2)
        bw = max(t, 20.0)
        bh = spec.bracket_height
        cz = board_cz - t / 2 - bh / 2
        for i in range(n):
            frac = (i + 0.5) / n
            x = -L / 2 + frac * L
            panels.append(PanelBox(
                f"Bracket {i + 1}", (bw, D * 0.8, bh), (x, D / 2, cz),
                "bracket", subassembly="Brackets"))
    return panels


def _wall_shelf_cutlist(spec: WallShelfSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    L, D, t = spec.length, spec.depth, spec.thickness
    cl.parts.append(Part(
        "Shelf board", 1, length=L, width=D, thickness=t,
        material=MAT_SOLID, grain="length", notes="shelf board"))

    fixing = spec.fixing
    if fixing == ShelfFixing.FRENCH_CLEAT:
        ch = spec.cleat_height
        cl.parts.append(Part(
            "Cleat", 2, length=L, width=ch, thickness=t, material=MAT_SOLID,
            grain="length", notes="45° bevel; one to wall, one to shelf"))
        cl.hardware.append(Hardware(
            hw.FRENCH_CLEAT.name, 1, hw.FRENCH_CLEAT.note, sku=hw.FRENCH_CLEAT.sku,
            category="connector"))
        cl.hardware.append(Hardware(
            hw.WALL_ANCHOR.name, max(int(L // 400) + 1, 2), hw.WALL_ANCHOR.note,
            sku=hw.WALL_ANCHOR.sku, category="fastener"))
    elif fixing == ShelfFixing.BRACKETS:
        n = max(spec.brackets, 2)
        cl.hardware.append(Hardware(
            hw.SHELF_BRACKET.name, n, hw.SHELF_BRACKET.note,
            sku=hw.SHELF_BRACKET.sku, category="connector"))
        cl.hardware.append(Hardware(
            hw.WALL_ANCHOR.name, n * 2, hw.WALL_ANCHOR.note,
            sku=hw.WALL_ANCHOR.sku, category="fastener"))
    else:  # hidden
        cl.hardware.append(Hardware(
            hw.HIDDEN_BRACKET.name, 1, hw.HIDDEN_BRACKET.note,
            sku=hw.HIDDEN_BRACKET.sku, category="connector"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _wall_shelf_validate(spec: WallShelfSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("length", "depth", "thickness", "height"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.thickness > spec.depth:
        warn("thickness", "shelf is thicker than it is deep; unusual proportions")
    if spec.fixing == ShelfFixing.BRACKETS and spec.brackets < 2:
        err("brackets", "a bracket-fixed shelf needs at least two brackets")

    # --- deflection: treat the shelf as a beam between its two end supports ----
    # A French cleat / two end brackets support the shelf near its ends, so the
    # span is roughly the full length. Reuse the same engineering check the
    # cabinet shelf uses, so the limits are consistent across the app.
    # Use the declared species' stiffness; with none given, fall back to the
    # conservative plywood modulus (a real solid board is usually stiffer).
    res = engineering.evaluate_shelf(
        span=spec.length, depth=spec.depth, thickness=spec.thickness,
        load_kg_per_m=spec.load_kg_per_m, species=(spec.species or "plywood"))
    if res.status == "fail":
        err("length",
            f"shelf will sag {res.deflection:.1f}mm over a {spec.length:.0f}mm span, "
            f"past the {res.engineering_limit:.1f}mm structural limit (span/360); "
            "shorten the span, thicken the board, or add a center bracket")
    elif res.status == "visible":
        warn("length",
             f"shelf sag {res.deflection:.1f}mm over {spec.length:.0f}mm will be "
             f"visible (> {res.visible_limit:.1f}mm); thicken the board, use a "
             "stiffer species, or add a center bracket")
    return issues


def _wall_shelf_joinery(spec: WallShelfSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops: list[JoineryOp] = []
    if spec.fixing == ShelfFixing.FRENCH_CLEAT:
        ops.append(JoineryOp(
            part="Cleat", operation="rip 45° bevel", tool="table saw (45°)",
            width=0.0, depth=round(spec.thickness, 1),
            reference="along the cleat length", part_id=pid("Cleat"),
            note="mating bevels: wall strip points up, shelf strip points down"))
    elif spec.fixing == ShelfFixing.HIDDEN:
        ops.append(JoineryOp(
            part="Shelf board", operation="bore for hidden rods",
            tool="drill (rod dia.)", width=0.0, depth=round(spec.depth * 0.7, 1),
            reference="into the rear edge", part_id=pid("Shelf board"),
            note="match the concealed-bracket rod diameter and spacing"))
    return ops


def _wall_shelf_assembly(spec: WallShelfSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    ids = [p.id for p in parts if p.id]
    hw_names = [h.name for h in cl.hardware]
    sub = SubAssembly("Wall shelf", "A board on a cleat or brackets",
                      part_ids=ids, category="carcass")
    sub.steps = [
        step(1, "Mill & finish the board",
              "Dimension the shelf board (and cleats), ease the edges, and apply "
              "the finish before mounting.", ids, category="prep"),
    ]
    if spec.fixing == ShelfFixing.FRENCH_CLEAT:
        sub.steps.append(step(
            2, "Cut & fit the French cleat",
            "Rip the 45° bevel pair; fix the wall strip level into studs and "
            "screw the shelf strip under the board's rear.", ids, hw_names,
            "hardware"))
        sub.steps.append(step(
            3, "Hang the shelf",
            "Drop the board's cleat onto the wall cleat — it self-registers and "
            "locks down.", category="hardware"))
    elif spec.fixing == ShelfFixing.BRACKETS:
        sub.steps.append(step(
            2, "Mount the brackets & shelf",
            "Anchor the brackets level into studs, then screw the board down to "
            "them.", ids, hw_names, "hardware"))
    else:
        sub.steps.append(step(
            2, "Fit the hidden brackets",
            "Anchor the concealed rods into the wall and slide the back-bored "
            "board onto them.", ids, hw_names, "hardware"))
    return [sub]


furniture.register(
    WALL_SHELF,
    panels=_wall_shelf_panels,
    cut_parts=_wall_shelf_cutlist,
    validate=_wall_shelf_validate,
    joinery_ops=_wall_shelf_joinery,
    assembly=_wall_shelf_assembly,
)


# ===========================================================================
# Box / chest
# ===========================================================================

# Corner joints that properly resist the box pulling apart (shared spirit with
# the drawer-box rule in the validator).
_STRONG_BOX_JOINTS = {"dovetail", "box", "rabbet", "locking_rabbet"}


def _box_panels(spec: BoxSpec) -> list[PanelBox]:
    """Four sides, a bottom, and (optionally) a lid, placed in the shared frame.

    X = width (centred), Y = depth (0 at the front face), Z = height (0 at the
    floor). The body rises to ``body_height``; the lid caps it.
    """
    W, D, t = spec.width, spec.depth, spec.thickness
    bh = spec.body_height
    panels: list[PanelBox] = []

    def add(label, size, center, unit="Box"):
        panels.append(PanelBox(label, size, center, "carcass", subassembly=unit))

    # Bottom sits between the sides, on the floor.
    add("Bottom", (W - 2 * t, D - 2 * t, t), (0.0, D / 2, t / 2))
    # Front / back run the full width; left / right between them.
    add("Front", (W, t, bh - t), (0.0, t / 2, t + (bh - t) / 2))
    add("Back", (W, t, bh - t), (0.0, D - t / 2, t + (bh - t) / 2))
    add("Side L", (t, D - 2 * t, bh - t),
        (-W / 2 + t / 2, D / 2, t + (bh - t) / 2))
    add("Side R", (t, D - 2 * t, bh - t),
        (W / 2 - t / 2, D / 2, t + (bh - t) / 2))

    if spec.lid:
        add("Lid", (W, D, t), (0.0, D / 2, bh + t / 2), unit="Lid")
    return panels


def _box_cutlist(spec: BoxSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    W, D, t = spec.width, spec.depth, spec.thickness
    bh = spec.body_height
    cj = str(spec.corner_joint).replace("_", " ")

    cl.parts.append(Part(
        "Front/back", 2, length=W, width=bh - t, thickness=t, material=MAT_SOLID,
        grain="length", notes=f"{cj} corners"))
    cl.parts.append(Part(
        "Side", 2, length=D - 2 * t, width=bh - t, thickness=t, material=MAT_SOLID,
        grain="length", notes=f"{cj} corners"))
    cl.parts.append(Part(
        "Bottom", 1, length=W - 2 * t, width=D - 2 * t, thickness=t,
        material=MAT_SOLID, grain="length", notes="captured in a groove"))
    if spec.lid:
        cl.parts.append(Part(
            "Lid", 1, length=W, width=D, thickness=t, material=MAT_SOLID,
            grain="length", notes="hinged lid"))
        n = max(spec.hinges, 2)
        cl.hardware.append(Hardware(
            hw.BUTT_HINGE.name, n, hw.BUTT_HINGE.note, sku=hw.BUTT_HINGE.sku,
            category="hardware"))
        cl.hardware.append(Hardware(
            hw.LID_SUPPORT.name, 1, hw.LID_SUPPORT.note, sku=hw.LID_SUPPORT.sku,
            category="hardware"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _box_validate(spec: BoxSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("width", "depth", "height", "thickness"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.body_height <= spec.thickness:
        err("height", "too short for a box body once the lid is removed")
    if 2 * spec.thickness >= min(spec.width, spec.depth):
        err("thickness", "walls are too thick to leave any interior")

    cj = str(spec.corner_joint).strip().lower()
    if cj == "butt":
        warn("corner_joint",
             "a butt-jointed box relies on end-grain glue and pulls apart; use "
             "dovetail, box joint, or a locking rabbet")
    elif cj not in _STRONG_BOX_JOINTS:
        warn("corner_joint",
             f"corner joint '{cj}' is weak for a box; prefer dovetail, box "
             "joint, or a locking rabbet")
    if spec.lid and spec.hinges < 2:
        warn("hinges", "a hinged lid usually needs at least two hinges")
    return issues


def _box_joinery(spec: BoxSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    t = spec.thickness
    cj = str(spec.corner_joint).strip().lower()
    ops: list[JoineryOp] = []
    if cj == "dovetail":
        ops.append(JoineryOp(
            part="Box corners", operation="dovetail corners",
            tool="dovetail jig / saw", width=0.0, depth=round(t, 1),
            reference="all four corners", part_id=pid("Front/back"),
            note="through or half-blind; tails on the sides"))
    elif cj == "box":
        ops.append(JoineryOp(
            part="Box corners", operation="box/finger joint",
            tool="box-joint jig", width=round(t, 1), depth=round(t, 1),
            reference="all four corners", part_id=pid("Front/back"),
            note="finger width = stock thickness"))
    elif cj in ("rabbet", "locking_rabbet"):
        ops.append(JoineryOp(
            part="Box corners", operation=f"{cj.replace('_', ' ')} corners",
            tool="dado / router", width=round(t, 1), depth=round(t * 0.5, 1),
            reference="all four corners", part_id=pid("Front/back"),
            note="glue + brad the rabbet"))
    else:
        ops.append(JoineryOp(
            part="Box corners", operation=f"{cj} corners",
            tool="doweling jig / glue", width=0.0, depth=0.0,
            reference="all four corners", part_id=pid("Front/back"),
            note="weak corner; prefer dovetail/box/locking rabbet"))
    # The bottom rides in a groove around the inside of the box.
    ops.append(JoineryOp(
        part="Box sides", operation="groove for bottom",
        tool="straight bit / dado", width=round(t, 1), depth=round(t * 0.5, 1),
        reference="~10mm up from the bottom edge", part_id=pid("Side"),
        note="captures the bottom panel"))
    if spec.lid:
        ops.append(JoineryOp(
            part="Lid / back", operation="hinge mortise",
            tool="chisel / router", width=0.0, depth=round(t * 0.3, 1),
            reference="rear edge", part_id=pid("Lid"),
            note="mortise the butt hinges flush"))
    return ops


def _box_assembly(spec: BoxSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    body_ids = [p.id for p in parts
                if p.id and p.name.lower() not in ("lid",)]
    lid_ids = [p.id for p in parts if p.id and p.name.lower() == "lid"]
    hw_names = [h.name for h in cl.hardware]

    body = SubAssembly("Box body", "Four sides and a captured bottom",
                       part_ids=body_ids, category="carcass")
    body.steps = [
        step(1, "Cut the corner joints & bottom groove",
              "Cut the chosen corner joint on all four corners and the groove "
              "for the bottom per the joinery sheet.", body_ids, category="joinery"),
        step(2, "Glue up the box",
              "Dry-fit, then glue and clamp the box square; slide the bottom into "
              "its groove and check it is flat and not in wind.", body_ids,
              category="carcass"),
    ]
    subs = [body]
    if spec.lid:
        lid = SubAssembly("Lid", "A hinged lid", part_ids=lid_ids,
                          category="fronts")
        lid.steps = [
            step(1, "Fit & hinge the lid",
                  "Trim the lid to fit, mortise the hinges into the lid and rear, "
                  "and hang it; add the lid stay.", lid_ids, hw_names, "hardware"),
        ]
        subs.append(lid)
    final = SubAssembly("Final", "Finish the chest", category="final")
    final.steps = [
        step(1, "Sand & finish",
              "Final-sand, ease the edges, and apply the finish.",
              category="finish"),
    ]
    subs.append(final)
    return subs


furniture.register(
    BOX,
    panels=_box_panels,
    cut_parts=_box_cutlist,
    validate=_box_validate,
    joinery_ops=_box_joinery,
    assembly=_box_assembly,
)


# ===========================================================================
# Bench / stool
# ===========================================================================

def _bench_leg_offsets(spec: BenchSpec) -> tuple[float, float]:
    """Leg-centre offsets (lx, ly) from the seat centre, like the table."""
    lx = spec.width / 2 - spec.leg_inset - spec.leg / 2
    ly = spec.depth / 2 - spec.leg_inset - spec.leg / 2
    return lx, ly


def _bench_panels(spec: BenchSpec) -> list[PanelBox]:
    """A seat, four legs, four aprons, and (optionally) lower stretchers.

    Mirrors the table layout (top + legs + aprons) and adds a stretcher along
    each long side between the leg pairs, set low for a seat that takes a
    sitting load. X = length, Y = depth, Z = height (seat top at ``height``).
    """
    W, D, H = spec.width, spec.depth, spec.height
    tt, leg = spec.top_thickness, spec.leg
    ah, at = spec.apron_height, spec.apron_thickness  # leg inset via _bench_leg_offsets
    panels: list[PanelBox] = []

    def add(label, size, center, category, unit=""):
        panels.append(PanelBox(label, size, center, category,
                               subassembly=unit or "Base"))

    add("Seat", (W, D, tt), (0, 0, H - tt / 2), "top", "Seat")

    leg_h = H - tt
    lx, ly = _bench_leg_offsets(spec)
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

    if spec.stretchers:
        sh, st = spec.stretcher_height, spec.stretcher_thickness
        sz = spec.stretcher_setback
        # One stretcher along each long side, between the front/back legs.
        for sy in (-1, 1):
            add("Stretcher", (apron_x, st, sh), (0, sy * ly, sz), "stretcher",
                "Stretchers")
    return panels


def _bench_cutlist(spec: BenchSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    leg_h = spec.height - spec.top_thickness
    lx, ly = _bench_leg_offsets(spec)
    apron_x = 2 * lx - spec.leg
    apron_y = 2 * ly - spec.leg

    cl.parts.append(Part(
        "Seat", 1, length=spec.width, width=spec.depth,
        thickness=spec.top_thickness, material=MAT_TOP, notes="solid/sheet seat"))
    cl.parts.append(Part(
        "Leg", 4, length=leg_h, width=spec.leg, thickness=spec.leg,
        material=MAT_LEG, notes="square stock"))
    cl.parts.append(Part(
        "Apron (long)", 2, length=apron_x, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    cl.parts.append(Part(
        "Apron (short)", 2, length=apron_y, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    if spec.stretchers:
        cl.parts.append(Part(
            "Stretcher", 2, length=apron_x, width=spec.stretcher_height,
            thickness=spec.stretcher_thickness, material=MAT_APRON,
            notes="lower rail, resists racking"))
    cl.hardware.append(Hardware("Corner bracket", 4, "leg-to-apron"))
    cl.hardware.append(Hardware("Seat fastener", 6, "expansion clip"))
    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _bench_validate(spec: BenchSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("width", "depth", "height", "top_thickness", "leg",
                 "apron_height", "apron_thickness", "leg_inset"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.height <= spec.top_thickness + spec.apron_height:
        err("height", "too short for the seat plus an apron")
    if 2 * spec.leg_inset + spec.leg >= min(spec.width, spec.depth):
        err("leg_inset", "legs do not fit within the seat with this inset")
    if spec.height < 300 or spec.height > 800:
        warn("height", "unusual seat height (benches ~400-460mm, stools ~600-760mm)")

    # Leg-to-apron joinery vs. racking — a seat takes a real load.
    joint = str(spec.joinery).strip().lower()
    if joint in ("pocket", "butt", "screw"):
        warn("joinery",
             f"a {joint.replace('_', ' ')} leg-to-apron joint racks under a "
             "sitting load; prefer mortise & tenon or domino, and keep the "
             "stretchers")
    if not spec.stretchers and spec.height > 500:
        warn("stretchers",
             "a tall stool without stretchers racks; add lower rails between "
             "the legs")
    return issues


def _bench_joinery(spec: BenchSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    j = str(spec.joinery).strip().lower()
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
    ops = [JoineryOp(
        part="Leg / apron", operation="leg-to-apron joint", tool=tool,
        width=w, depth=d, reference="apron into leg", part_id=pid("Leg"),
        note=note)]
    if spec.stretchers:
        ops.append(JoineryOp(
            part="Leg / stretcher", operation="leg-to-stretcher joint",
            tool=tool, width=w, depth=d, reference="stretcher into leg",
            part_id=pid("Stretcher"), note="lower rail tenons into the leg"))
    return ops


def _bench_assembly(spec: BenchSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    legs = [p.id for p in parts if p.id and "leg" in p.name.lower()]
    aprons = [p.id for p in parts if p.id and "apron" in p.name.lower()]
    stretchers = [p.id for p in parts if p.id and "stretcher" in p.name.lower()]
    seat = [p.id for p in parts if p.id and p.name.lower() == "seat"]
    base_ids = sorted(set(legs + aprons + stretchers))

    base = SubAssembly("Base", "Four legs joined by aprons and stretchers",
                       part_ids=base_ids, category="carcass")
    base.steps = [
        step(1, "Cut the leg joints",
              "Mortise the legs and tenon the aprons and stretchers (or Domino/"
              "dowel) per the joinery sheet.", base_ids, category="joinery"),
        step(2, "Glue up the base",
              "Glue the two end assemblies (legs + short aprons + stretchers), "
              "then join with the long rails; check for square and wind.",
              base_ids, category="carcass"),
    ]
    seat_sub = SubAssembly("Seat", "The seat top", part_ids=seat,
                           category="carcass")
    seat_sub.steps = [
        step(1, "Prepare the seat",
              "Edge-glue the boards into a flat panel (or dimension the sheet) "
              "and sand level.", seat, category="carcass"),
    ]
    final = SubAssembly("Final assembly", "Join seat to base and finish",
                        category="final")
    final.steps = [
        step(1, "Attach the seat",
              "Fasten the seat to the base allowing for seasonal movement "
              "(figure-8 fasteners / Z-clips).", seat, ["Seat fastener"],
              "hardware"),
        step(2, "Sand & finish", "Final-sand and apply the finish.",
              category="finish"),
    ]
    return [base, seat_sub, final]


furniture.register(
    BENCH,
    panels=_bench_panels,
    cut_parts=_bench_cutlist,
    validate=_bench_validate,
    joinery_ops=_bench_joinery,
    assembly=_bench_assembly,
)


# ===========================================================================
# Picture / mirror frame
# ===========================================================================

# Corner joints that actually hold a frame together (a plain glued miter is
# end-grain on end-grain and opens over time).
_STRONG_FRAME_JOINTS = {"splined_miter", "half_lap", "cope_stick"}


def _frame_panels(spec: FrameSpec) -> list[PanelBox]:
    """Four rails around the opening, placed in the shared frame.

    X = width (centred on 0), Y = depth (front face at 0, +Y toward the wall),
    Z = height (frame foot at 0). Top/bottom rails run the full outer width;
    the side rails fill between them — so the four boxes tile the frame face
    with no overlap (the positive-volume check stays clean).
    """
    ow, oh = spec.outer_w, spec.outer_h
    mw, mt = spec.molding_width, spec.molding_thickness
    cy = mt / 2

    def rail(label, size, center):
        return PanelBox(label, size, center, "frame", subassembly="Frame")

    return [
        rail("Rail top", (ow, mt, mw), (0.0, cy, oh - mw / 2)),
        rail("Rail bottom", (ow, mt, mw), (0.0, cy, mw / 2)),
        rail("Rail left", (mw, mt, oh - 2 * mw),
             (-(ow / 2 - mw / 2), cy, oh / 2)),
        rail("Rail right", (mw, mt, oh - 2 * mw),
             (ow / 2 - mw / 2, cy, oh / 2)),
    ]


def _frame_has_glazing(spec: FrameSpec) -> bool:
    """True when something rides in the rabbet (glass/acrylic, art, or mirror)."""
    return spec.contents != FrameContents.NONE or \
        str(spec.glazing).strip().lower() != "none"


def _frame_cutlist(spec: FrameSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    ow, oh = spec.outer_w, spec.outer_h
    mw, mt = spec.molding_width, spec.molding_thickness
    cj = str(spec.corner_joint).replace("_", " ")

    # All four rails share the molding cross-section; they differ only in length.
    cl.parts.append(Part(
        "Rail (top/bottom)", 2, length=ow, width=mw, thickness=mt,
        material=MAT_SOLID, grain="length",
        notes=f"{cj} corners; rabbet on the inner back edge"))
    cl.parts.append(Part(
        "Rail (side)", 2, length=oh, width=mw, thickness=mt,
        material=MAT_SOLID, grain="length",
        notes=f"{cj} corners; rabbet on the inner back edge"))

    # Corner reinforcement for a splined miter.
    if spec.corner_joint == FrameJoint.SPLINED_MITER:
        cl.hardware.append(Hardware(
            hw.FRAME_CORNER_SPLINE.name, 4, hw.FRAME_CORNER_SPLINE.note,
            sku=hw.FRAME_CORNER_SPLINE.sku, category="joinery"))

    # Glazing / mirror + backer (sized to the rabbet) and the retainers.
    if _frame_has_glazing(spec):
        size = f"{spec.glazing_w:.0f}×{spec.glazing_h:.0f}mm"
        if spec.contents == FrameContents.MIRROR:
            cl.hardware.append(Hardware(
                "Mirror", 1, f"silvered glass, {size}", sku=hw.FRAME_GLAZING.sku,
                category="material"))
        elif str(spec.glazing).strip().lower() != "none":
            cl.hardware.append(Hardware(
                f"Glazing ({spec.glazing})", 1, f"cut to the rabbet, {size}",
                sku=hw.FRAME_GLAZING.sku, category="material"))
        cl.hardware.append(Hardware(
            hw.FRAME_BACKER.name, 1, f"{size}", sku=hw.FRAME_BACKER.sku,
            category="material"))
        # Retainers about every 150mm of the inner perimeter.
        perim = 2 * (spec.opening_w + spec.opening_h)
        cl.hardware.append(Hardware(
            hw.GLAZIER_POINT.name, max(4, int(perim // 150)),
            hw.GLAZIER_POINT.note, sku=hw.GLAZIER_POINT.sku, category="fastener"))

    # Hanging hardware.
    if spec.hanger == FrameHanger.SAWTOOTH:
        cl.hardware.append(Hardware(
            hw.SAWTOOTH_HANGER.name, 1, hw.SAWTOOTH_HANGER.note,
            sku=hw.SAWTOOTH_HANGER.sku, category="hardware"))
    elif spec.hanger == FrameHanger.CLEAT:
        cl.hardware.append(Hardware(
            hw.FRENCH_CLEAT.name, 1, hw.FRENCH_CLEAT.note,
            sku=hw.FRENCH_CLEAT.sku, category="connector"))
        cl.hardware.append(Hardware(
            hw.WALL_ANCHOR.name, 2, hw.WALL_ANCHOR.note, sku=hw.WALL_ANCHOR.sku,
            category="fastener"))
    else:  # d_ring_wire
        cl.hardware.append(Hardware(
            hw.D_RING.name, 2, hw.D_RING.note, sku=hw.D_RING.sku,
            category="hardware"))
        cl.hardware.append(Hardware(
            hw.HANGING_WIRE.name, 1, hw.HANGING_WIRE.note,
            sku=hw.HANGING_WIRE.sku, category="hardware"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _frame_validate(spec: FrameSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("opening_w", "opening_h", "molding_width", "molding_thickness",
                 "rabbet_width", "rabbet_depth"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.rabbet_depth >= spec.molding_thickness:
        err("rabbet_depth",
            "rabbet is as deep as the molding is thick — it would cut the rail "
            "in two; make the molding thicker or the rabbet shallower")
    if spec.rabbet_width >= spec.molding_width:
        err("rabbet_width",
            "rabbet is as wide as the rail face — nothing is left to show; "
            "widen the molding or narrow the rabbet")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.rabbet_depth < 6:
        warn("rabbet_depth",
             "a rabbet under ~6mm struggles to hold glazing + art + backer; "
             "deepen it or use thinner glazing")

    cj = str(spec.corner_joint).strip().lower()
    big = max(spec.outer_w, spec.outer_h) > 600
    if cj == "miter":
        if big:
            warn("corner_joint",
                 "a plain glued miter on a large frame opens at the corners as "
                 "the wood moves; add a spline/V-nail (splined_miter) or use a "
                 "half-lap")
        else:
            warn("corner_joint",
                 "a plain glued miter is end-grain-weak; reinforce it with a "
                 "spline or V-nails (splined_miter)")
    elif cj not in _STRONG_FRAME_JOINTS:
        warn("corner_joint",
             f"corner joint '{cj}' is weak for a frame; prefer a splined miter, "
             "half-lap, or cope-and-stick")

    if spec.contents == FrameContents.MIRROR and \
            spec.hanger == FrameHanger.SAWTOOTH:
        warn("hanger",
             "a mirror is heavy for a single sawtooth hanger; use D-rings + wire "
             "or a French cleat anchored into a stud")
    if spec.contents == FrameContents.ART and \
            str(spec.glazing).strip().lower() == "none":
        warn("glazing",
             "art with no glazing is left exposed; add glass or acrylic unless a "
             "bare canvas is intended")
    return issues


def _frame_joinery(spec: FrameSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    cj = str(spec.corner_joint).strip().lower()
    ops: list[JoineryOp] = []
    if cj == "splined_miter":
        ops.append(JoineryOp(
            part="Frame corners", operation="splined miter",
            tool="miter sled + spline jig", width=round(spec.molding_width / 6, 1),
            depth=round(spec.molding_width * 0.5, 1), reference="all four corners",
            part_id=pid("Rail (top/bottom)"),
            note="45° miters, then a kerf across each corner for a contrasting spline"))
    elif cj == "half_lap":
        ops.append(JoineryOp(
            part="Frame corners", operation="half-lap corners",
            tool="dado / router", width=round(spec.molding_width, 1),
            depth=round(spec.molding_thickness / 2, 1),
            reference="all four corners", part_id=pid("Rail (top/bottom)"),
            note="overlapping half-laps; glue and clamp flat"))
    elif cj == "cope_stick":
        ops.append(JoineryOp(
            part="Frame corners", operation="cope-and-stick",
            tool="router table (rail-and-stile set)", width=0.0,
            depth=round(spec.rabbet_depth, 1), reference="all four corners",
            part_id=pid("Rail (top/bottom)"),
            note="stick the profile, cope the mating ends"))
    else:  # plain miter
        ops.append(JoineryOp(
            part="Frame corners", operation="45° miters",
            tool="miter saw / sled", width=0.0, depth=round(spec.molding_thickness, 1),
            reference="all four corners", part_id=pid("Rail (top/bottom)"),
            note="glue + band clamp (reinforce with V-nails)"))
    # The rabbet that holds the glazing/art/backer.
    ops.append(JoineryOp(
        part="Frame rails", operation="rabbet for glazing",
        tool="router / dado", width=round(spec.rabbet_width, 1),
        depth=round(spec.rabbet_depth, 1), reference="inner back edge, all rails",
        part_id=pid("Rail (side)"),
        note="holds glazing + art/mirror + backer"))
    return ops


def _frame_assembly(spec: FrameSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    rail_ids = [p.id for p in parts if p.id]
    glaze_hw = [h.name for h in cl.hardware
                if h.category in ("material", "fastener", "joinery")]
    hang_hw = [h.name for h in cl.hardware
               if h.category in ("hardware", "connector")]

    frame = SubAssembly("Frame", "Four mitered rails with a glazing rabbet",
                        part_ids=rail_ids, category="carcass")
    frame.steps = [
        step(1, "Mill the molding & cut the rabbet",
              "Dimension the molding stock and rout the rabbet along the inner "
              "back edge before cutting the rails to length.", rail_ids,
              category="prep"),
        step(2, "Cut the corner joints",
              "Cut the corners per the joinery sheet — accurate 45° miters (or "
              "half-laps/cope-and-stick).", rail_ids, category="joinery"),
        step(3, "Glue up & check square",
              "Dry-fit, then glue and band-clamp the frame; check the diagonals "
              "are equal before the glue sets and reinforce the corners "
              "(spline / V-nails).", rail_ids, glaze_hw, "carcass"),
    ]
    glaze = SubAssembly("Glazing & backer", "Fit the glass, art, and backer",
                        category="fronts")
    if _frame_has_glazing(spec):
        glaze.steps = [
            step(1, "Glaze & back the frame",
                  "Clean and drop in the glazing, then the art/mirror and backer; "
                  "retain them with glazier points or turn buttons.", [], glaze_hw,
                  "hardware"),
        ]
    else:
        glaze.steps = [
            step(1, "Leave the opening open",
                  "No glazing — ease the rabbet and move on to finishing.",
                  category="prep"),
        ]
    final = SubAssembly("Finish & hang", "Finish the frame and add the hanger",
                        category="final")
    final.steps = [
        step(1, "Sand & finish",
              "Final-sand, ease the edges, and apply the finish before glazing if "
              "a film finish might cloud the glass.", rail_ids, category="finish"),
        step(2, "Fit the hanger",
              "Attach the hanging hardware to the back, centred and level.",
              [], hang_hw, "hardware"),
    ]
    return [frame, glaze, final]


furniture.register(
    FRAME,
    panels=_frame_panels,
    cut_parts=_frame_cutlist,
    validate=_frame_validate,
    joinery_ops=_frame_joinery,
    assembly=_frame_assembly,
)


# ===========================================================================
# Bed (knock-down: headboard + footboard + side rails + slat deck)
# ===========================================================================

def _bed_dims(spec: BedSpec) -> dict:
    """Shared bed geometry so panels and the cut list never disagree.

    X = width (centred), Y = length (head at 0, foot at +depth), Z = height.
    The posts and rails share an outer face at ``outer_x``; the head/foot infill
    spans between the posts' inner faces.
    """
    iw = spec.inner_width
    rt = spec.rail_thickness
    p = spec.post
    outer_x = iw / 2 + rt
    depth = spec.depth
    post_cx = outer_x - p / 2          # post outer face flush with the rail
    rail_cx = outer_x - rt / 2
    inner_post_span = max(2 * (outer_x - p), 0.0)
    head_cap = min(80.0, spec.head_height * 0.2)
    foot_cap = min(80.0, spec.foot_height * 0.2)
    return {
        "iw": iw, "rt": rt, "p": p, "outer_x": outer_x, "depth": depth,
        "post_cx": post_cx, "rail_cx": rail_cx, "inner_post_span": inner_post_span,
        "rail_len_y": depth - 2 * p, "head_cap": head_cap, "foot_cap": foot_cap,
        "slat_w": 65.0, "slat_t": 18.0, "ledger": 25.0, "panel_t": 18.0,
    }


def _bed_panels(spec: BedSpec) -> list[PanelBox]:
    g = _bed_dims(spec)
    p, depth = g["p"], g["depth"]
    dh, rh = spec.deck_height, spec.rail_height
    panels: list[PanelBox] = []

    def add(label, size, center, category, unit):
        panels.append(PanelBox(label, size, center, category, subassembly=unit))

    # Four posts (head pair tall, foot pair short).
    for sx in (-1, 1):
        add("Post head", (p, p, spec.head_height),
            (sx * g["post_cx"], p / 2, spec.head_height / 2), "leg", "Headboard")
        add("Post foot", (p, p, spec.foot_height),
            (sx * g["post_cx"], depth - p / 2, spec.foot_height / 2),
            "leg", "Footboard")

    # Head / foot top rails between the posts.
    add("Rail head", (g["inner_post_span"], p, g["head_cap"]),
        (0.0, p / 2, spec.head_height - g["head_cap"] / 2), "apron", "Headboard")
    add("Rail foot", (g["inner_post_span"], p, g["foot_cap"]),
        (0.0, depth - p / 2, spec.foot_height - g["foot_cap"] / 2),
        "apron", "Footboard")

    # Head / foot infill panels (frame-and-panel modelled as a recessed slab).
    if spec.panel:
        ph_head = spec.head_height - g["head_cap"] - dh
        if ph_head > 0:
            add("Headboard panel", (g["inner_post_span"], g["panel_t"], ph_head),
                (0.0, p / 2, dh + ph_head / 2), "carcass", "Headboard")
        ph_foot = spec.foot_height - g["foot_cap"] - dh
        if ph_foot > 0:
            add("Footboard panel", (g["inner_post_span"], g["panel_t"], ph_foot),
                (0.0, depth - p / 2, dh + ph_foot / 2), "carcass", "Footboard")

    # Two side rails between the posts, tops at the deck height.
    for sx in (-1, 1):
        add("Side rail", (g["rt"], g["rail_len_y"], rh),
            (sx * g["rail_cx"], depth / 2, dh - rh / 2), "apron", "Rails")

    # Slat deck spanning between the rail inner faces, distributed along Y.
    n = spec.slat_count
    sw, st = g["slat_w"], g["slat_t"]
    y0, y1 = p, depth - p
    if n > 1:
        for i in range(n):
            frac = i / (n - 1)
            y = y0 + sw / 2 + frac * (y1 - y0 - sw)
            add(f"Slat {i + 1}", (g["iw"], sw, st), (0.0, y, dh - st / 2),
                "shelf", "Slats")
    return panels


def _bed_cutlist(spec: BedSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    g = _bed_dims(spec)
    p = g["p"]

    cl.parts.append(Part(
        "Post (head)", 2, length=spec.head_height, width=p, thickness=p,
        material=MAT_LEG, notes="square head post, mortised for rail + panel"))
    cl.parts.append(Part(
        "Post (foot)", 2, length=spec.foot_height, width=p, thickness=p,
        material=MAT_LEG, notes="square foot post"))
    cl.parts.append(Part(
        "Side rail", 2, length=g["rail_len_y"], width=spec.rail_height,
        thickness=spec.rail_thickness, material=MAT_APRON, grain="length",
        notes="knock-down to the posts; carries the slat ledger"))
    cl.parts.append(Part(
        "Rail (head)", 1, length=g["inner_post_span"], width=g["head_cap"],
        thickness=p, material=MAT_APRON, grain="length", notes="headboard top rail"))
    cl.parts.append(Part(
        "Rail (foot)", 1, length=g["inner_post_span"], width=g["foot_cap"],
        thickness=p, material=MAT_APRON, grain="length", notes="footboard top rail"))
    if spec.panel:
        ph_head = spec.head_height - g["head_cap"] - spec.deck_height
        if ph_head > 0:
            cl.parts.append(Part(
                "Headboard panel", 1, length=g["inner_post_span"], width=ph_head,
                thickness=g["panel_t"], material=MAT_SOLID_PANEL, grain="width",
                notes="floating panel in the post/rail grooves (or frame-and-panel)"))
        ph_foot = spec.foot_height - g["foot_cap"] - spec.deck_height
        if ph_foot > 0:
            cl.parts.append(Part(
                "Footboard panel", 1, length=g["inner_post_span"], width=ph_foot,
                thickness=g["panel_t"], material=MAT_SOLID_PANEL, grain="width",
                notes="floating panel"))
    cl.parts.append(Part(
        "Slat", spec.slat_count, length=g["iw"], width=g["slat_w"],
        thickness=g["slat_t"], material=MAT_SOLID, grain="length",
        notes="cross slat resting on the rail ledgers"))
    cl.parts.append(Part(
        "Slat ledger", 2, length=g["rail_len_y"], width=g["ledger"],
        thickness=g["ledger"], material=MAT_SOLID, grain="length",
        notes="screwed inside each side rail to carry the slats"))

    # Knock-down rail connectors (one corner = one joint, four joints).
    if spec.connector == BedConnector.BED_BOLT:
        cl.hardware.append(Hardware(
            hw.BED_BOLT.name, 4, hw.BED_BOLT.note, sku=hw.BED_BOLT.sku,
            category="connector"))
        cl.hardware.append(Hardware(
            hw.BED_BOLT_COVER.name, 4, hw.BED_BOLT_COVER.note,
            sku=hw.BED_BOLT_COVER.sku, category="hardware"))
    else:  # hook plates
        cl.hardware.append(Hardware(
            hw.BED_HOOK_PLATE.name, 4, hw.BED_HOOK_PLATE.note,
            sku=hw.BED_HOOK_PLATE.sku, category="connector"))
    cl.hardware.append(Hardware(
        hw.ASSEMBLY_SCREW.name, spec.slat_count + 8, hw.ASSEMBLY_SCREW.note,
        sku=hw.ASSEMBLY_SCREW.sku, category="fastener"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _bed_validate(spec: BedSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("post", "head_height", "foot_height", "deck_height",
                 "rail_height", "rail_thickness"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if str(spec.size) == "custom" and not (
            _finite_positive(spec.mattress_w) and _finite_positive(spec.mattress_l)):
        err("size", "a custom bed needs positive mattress_w and mattress_l")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.deck_height + spec.rail_height > spec.foot_height:
        warn("foot_height",
             "the foot posts are shorter than the rail/deck — the rail will stand "
             "proud of the footboard; raise foot_height or lower deck_height")
    if spec.head_height <= spec.deck_height:
        err("head_height", "head posts are shorter than the slat deck height")
    if spec.foot_height > spec.head_height:
        warn("foot_height", "the footboard is taller than the headboard (unusual)")
    if spec.deck_height < 120 or spec.deck_height > 600:
        warn("deck_height",
             "unusual deck height (platform decks ~200-300mm; with box-spring "
             "~150mm)")

    # Slat-deck deflection: a slat is a beam spanning the clear inner width under
    # a share of the sleeping load. Reuse the same shelf engineering check.
    g = _bed_dims(spec)
    load_per_slat_kg = 180.0 / max(spec.slat_count, 1)        # ~2 sleepers + mattress
    load_kg_per_m = load_per_slat_kg / max(g["iw"] / 1000.0, 0.1)
    res = engineering.evaluate_shelf(
        span=g["iw"], depth=g["slat_w"], thickness=g["slat_t"],
        load_kg_per_m=load_kg_per_m, species=(spec.species or "pine"))
    if res.status == "fail" or spec.inner_width > 1500:
        warn("slats",
             "a wide deck sags under load — add a centre support rail on a foot "
             "(or thicker/closer slats) for a queen/king")
    return issues


def _bed_joinery(spec: BedSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops: list[JoineryOp] = []
    # Head/foot rails tenon into the posts (this part IS glued up).
    ops.append(JoineryOp(
        part="Rail / post", operation="mortise & tenon",
        tool="mortiser / saw", width=round(spec.post / 3, 1),
        depth=round(spec.post * 0.6, 1), reference="head & foot rails into posts",
        part_id=pid("Post (head)"), note="glued headboard/footboard frame"))
    if spec.panel:
        ops.append(JoineryOp(
            part="Posts / rails", operation="groove for panel",
            tool="router / dado", width=round(_bed_dims(spec)["panel_t"], 1),
            depth=12.0, reference="inner edges of the head/foot frame",
            part_id=pid("Rail (head)"), note="floating panel, ~2mm expansion gap"))
    # Side rail to post: the knock-down connector (NOT glued).
    if spec.connector == BedConnector.BED_BOLT:
        ops.append(JoineryOp(
            part="Side rail / post", operation="bed-bolt bore + cross-dowel",
            tool="drill (bolt + dowel dia.)", width=0.0,
            depth=round(spec.post + 40, 1), reference="through the post into the rail end",
            part_id=pid("Side rail"),
            note="counterbore the post face; cross-dowel nut in the rail — knock-down"))
    else:
        ops.append(JoineryOp(
            part="Side rail / post", operation="hook-plate mortise",
            tool="router / chisel", width=round(spec.rail_thickness, 1),
            depth=6.0, reference="rail end & post face",
            part_id=pid("Side rail"), note="recess the interlocking bed-rail brackets"))
    # Ledger that carries the slats.
    ops.append(JoineryOp(
        part="Side rail / ledger", operation="screw the slat ledger",
        tool="drill / driver", width=0.0, depth=round(spec.rail_thickness / 2, 1),
        reference="along the inside of each side rail", part_id=pid("Slat ledger"),
        note="glue + screw; sets the deck height"))
    return ops


def _bed_assembly(spec: BedSpec, cl) -> list[SubAssembly]:
    parts = cl.parts

    def ids(*subs):
        out = []
        for p in parts:
            if p.id and any(s in p.name.lower() for s in subs):
                out.append(p.id)
        return out

    head_ids = ids("post (head)", "rail (head)", "headboard")
    foot_ids = ids("post (foot)", "rail (foot)", "footboard")
    rail_ids = ids("side rail", "ledger")
    slat_ids = ids("slat")
    conn_hw = [h.name for h in cl.hardware if h.category == "connector"]

    head = SubAssembly("Headboard", "Posts, top rail, and infill panel",
                       part_ids=head_ids, category="carcass")
    head.steps = [
        step(1, "Cut the headboard joinery",
              "Mortise the head posts and tenon the head rail; groove for the "
              "panel if used.", head_ids, category="joinery"),
        step(2, "Glue up the headboard",
              "Dry-fit, then glue and clamp the headboard square with the panel "
              "floating in its grooves (do not glue the panel).", head_ids,
              category="carcass"),
    ]
    foot = SubAssembly("Footboard", "Posts, top rail, and infill panel",
                       part_ids=foot_ids, category="carcass")
    foot.steps = [
        step(1, "Build the footboard",
              "Repeat the headboard joinery and glue-up for the shorter "
              "footboard.", foot_ids, category="carcass"),
    ]
    rails = SubAssembly("Rails", "Side rails with slat ledgers + KD hardware",
                        part_ids=rail_ids, category="carcass")
    rails.steps = [
        step(1, "Fit the ledgers & knock-down hardware",
              "Glue and screw a ledger inside each side rail at the deck height, "
              "then install the bed bolts / hook plates at the rail ends.",
              rail_ids, conn_hw, "hardware"),
    ]
    final = SubAssembly("Set up & deck", "Assemble the bed and lay the slats",
                        part_ids=slat_ids, category="final")
    final.steps = [
        step(1, "Finish the parts",
              "Final-sand and finish the headboard, footboard, rails and slats "
              "before assembly.", category="finish"),
        step(2, "Bolt it together & lay the slats",
              "Stand the head/footboard, connect the side rails with the "
              "knock-down hardware (no glue — it must come apart), and drop the "
              "slats onto the ledgers.", slat_ids, conn_hw, "hardware"),
    ]
    return [head, foot, rails, final]


furniture.register(
    BED,
    panels=_bed_panels,
    cut_parts=_bed_cutlist,
    validate=_bed_validate,
    joinery_ops=_bed_joinery,
    assembly=_bed_assembly,
)


# ===========================================================================
# Cutting / charcuterie board (edge-glued strip panel)
# ===========================================================================

_FOOD_SAFE_FINISHES = {"oil", "none", ""}        # film finishes aren't food-safe


def _board_panels(spec: CuttingBoardSpec) -> list[PanelBox]:
    """The board modelled as its edge-glued strips, side by side across X.

    X = width (strips tile it), Y = length, Z = thickness (board on the bench).
    """
    n, sw = spec.strip_count, spec.strip_width
    L, t, W = spec.length, spec.thickness, spec.width
    panels: list[PanelBox] = []
    for i in range(n):
        x = -W / 2 + (i + 0.5) * sw
        panels.append(PanelBox(
            f"Strip {i + 1}", (sw, L, t), (x, L / 2, t / 2), "top",
            subassembly="Board"))
    return panels


def _board_cutlist(spec: CuttingBoardSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    n = spec.strip_count
    two = bool(spec.species_b)
    end = spec.grain_style == GrainStyle.END_GRAIN
    # A little length for trimming the glued blank square; end grain needs more.
    allow = 40.0 if end else 25.0
    note = "edge-glued strip" + ("; crosscut & re-glue for end grain" if end else "")

    if two:
        n_a = (n + 1) // 2
        n_b = n // 2
        cl.parts.append(Part(
            f"Strip — {spec.species}", n_a, length=spec.length + allow,
            width=spec.strip_width, thickness=spec.thickness, material=MAT_SOLID,
            grain="length", notes=note))
        cl.parts.append(Part(
            f"Strip — {spec.species_b}", n_b, length=spec.length + allow,
            width=spec.strip_width, thickness=spec.thickness, material=MAT_SOLID,
            grain="length", notes=note))
    else:
        cl.parts.append(Part(
            "Strip", n, length=spec.length + allow, width=spec.strip_width,
            thickness=spec.thickness, material=MAT_SOLID, grain="length",
            notes=note))

    if spec.feet:
        cl.hardware.append(Hardware(
            hw.BOARD_FOOT.name, 4, hw.BOARD_FOOT.note, sku=hw.BOARD_FOOT.sku,
            category="hardware"))
    cl.hardware.append(Hardware(
        hw.BOARD_OIL.name, 1, hw.BOARD_OIL.note, sku=hw.BOARD_OIL.sku,
        category="finish"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _board_validate(spec: CuttingBoardSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    for name in ("length", "width", "thickness"):
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    end = spec.grain_style == GrainStyle.END_GRAIN
    if end and spec.thickness < 32:
        warn("thickness",
             "an end-grain board under ~32mm is fragile and prone to splitting; "
             "go thicker")
    elif not end and spec.thickness < 18:
        warn("thickness",
             "a board under ~18mm cups and feels flimsy; aim for 18-40mm")
    if spec.juice_groove and spec.thickness < 25:
        warn("juice_groove",
             "too thin for a juice groove without weakening the board; thicken it "
             "or drop the groove")
    if str(spec.finish).strip().lower() not in _FOOD_SAFE_FINISHES:
        warn("finish",
             "use a food-safe finish (mineral oil / board butter), not a film "
             "finish like paint or polyurethane")
    # Open-pore species trap food/bacteria; steer to tight-grain woods.
    if species.finishing_category(spec.species) == species.FINISH_OPEN_PORE:
        warn("species",
             f"{spec.species} is open-pored — it traps food and bacteria; prefer "
             "tight-grain maple, walnut, cherry, or beech for a board")
    return issues


def _board_joinery(spec: CuttingBoardSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    label = cl.parts[0].name if cl.parts else "Strip"
    ops = [JoineryOp(
        part="Strips", operation="edge glue-up", tool="jointer + clamps",
        width=0.0, depth=round(spec.thickness, 1), reference="strip to strip",
        part_id=pid(label), note="alternate the grain/colour; cauls keep it flat")]
    if spec.grain_style == GrainStyle.END_GRAIN:
        ops.append(JoineryOp(
            part="Blank", operation="crosscut & re-glue (end grain)",
            tool="crosscut sled + clamps", width=0.0, depth=round(spec.thickness, 1),
            reference="rotate the strips 90° end-up", part_id=pid(label),
            note="second glue-up brings the end grain to the surface"))
    if spec.juice_groove:
        ops.append(JoineryOp(
            part="Board", operation="rout juice groove", tool="router + round-nose bit",
            width=8.0, depth=6.0, reference="~20mm in from the perimeter",
            part_id=pid(label), note="catches juices; keep clear of the edge"))
    if spec.chamfer > 0:
        ops.append(JoineryOp(
            part="Board", operation="ease the edges", tool="router / block plane",
            width=round(spec.chamfer, 1), depth=round(spec.chamfer, 1),
            reference="all top & bottom edges", part_id=pid(label),
            note="a chamfer or round-over is kinder on the hands"))
    return ops


def _board_assembly(spec: CuttingBoardSpec, cl) -> list[SubAssembly]:
    ids = [p.id for p in cl.parts if p.id]
    hw_names = [h.name for h in cl.hardware]
    end = spec.grain_style == GrainStyle.END_GRAIN

    glue = SubAssembly("Glue-up", "Edge-glue the strips into a panel",
                       part_ids=ids, category="carcass")
    glue.steps = [
        step(1, "Mill & arrange the strips",
              "Dimension the strips, joint a clean edge on each, and lay out the "
              "pattern (alternate species/grain).", ids, category="prep"),
        step(2, "Glue up the panel",
              "Glue and clamp the strips with cauls to keep the panel flat; "
              "don't starve the joints.", ids, category="carcass"),
    ]
    subs = [glue]
    if end:
        eg = SubAssembly("End grain", "Crosscut and re-glue end-up",
                         category="carcass")
        eg.steps = [
            step(1, "Crosscut & re-glue",
                  "Flatten the blank, crosscut it into strips across the glue "
                  "lines, rotate each 90° so the end grain faces up, and glue up "
                  "again.", category="carcass"),
        ]
        subs.append(eg)
    final = SubAssembly("Flatten & finish", "Flatten, shape, and oil the board",
                        category="final")
    fsteps = [
        step(1, "Flatten & ease the edges",
              "Flatten both faces (plane/sand or a router sled), then chamfer or "
              "round-over the edges.", category="finish"),
    ]
    if spec.juice_groove:
        fsteps.append(step(2, "Rout the juice groove",
                           "Rout the perimeter juice groove with a round-nose bit.",
                           category="finish"))
    fsteps.append(step(len(fsteps) + 1, "Sand & oil",
                       "Sand to ~220, raise the grain with water, knock it back, "
                       "then flood with food-safe oil and finish with board "
                       "butter.", [], hw_names, "finish"))
    if spec.feet:
        fsteps.append(step(len(fsteps) + 1, "Add the feet",
                           "Fit non-slip feet to the underside for grip and "
                           "airflow.", [], ["Rubber / silicone board feet"],
                           "hardware"))
    final.steps = fsteps
    subs.append(final)
    return subs


furniture.register(
    CUTTING_BOARD,
    panels=_board_panels,
    cut_parts=_board_cutlist,
    validate=_board_validate,
    joinery_ops=_board_joinery,
    assembly=_board_assembly,
)


# ===========================================================================
# Shared helpers for legged furniture (nightstand / desk / workbench)
# ===========================================================================

def _legged_offsets(width: float, depth: float, leg_inset: float,
                    leg: float) -> tuple[float, float]:
    """Leg-centre offsets (lx, ly) from the top centre — front is at -Y."""
    lx = width / 2 - leg_inset - leg / 2
    ly = depth / 2 - leg_inset - leg / 2
    return lx, ly


def _drawer_cut_parts(cl: CutList, n: int, opening_w: float, box_depth: float,
                      front_h: float, *, pull: str = "knob") -> None:
    """Append cut-list parts + hardware for *n* identical apron-hung drawers.

    A simple four-side box (sides + front/back + a captured ply bottom) on a
    ball-bearing slide pair per drawer, behind an overlay/inset drawer front.
    """
    if n <= 0:
        return
    bt = 12.0                       # box wall thickness (solid-wood drawer box)
    bottom_t = 6.0                  # captured ply bottom
    # Box width/height come from the one shared helper so these apron-hung
    # drawers can't drift from cabinet drawers (this path used to hardcode a
    # 13.0 side clearance and a 25mm height drop — the very conflict the
    # constants unification retired in favour of SLIDE_SIDE_CLEARANCE=12.7 and
    # DRAWER_BOX_HEIGHT_DROP=40.0). Depth is supplied by the caller (the apron
    # opening already bounds it), so the helper's depth result is unused.
    box_w, box_h, _ = drawer_box_dims(
        opening_w, front_h, box_depth, width_floor=MIN_DRAWER_BOX_WIDTH_3D)
    cl.parts.append(Part(
        "Drawer front", n, length=opening_w, width=front_h, thickness=18.0,
        material=MAT_DOOR_FRONT, grain="length", notes="drawer face"))
    cl.parts.append(Part(
        "Drawer side", 2 * n, length=box_depth, width=box_h, thickness=bt,
        material=MAT_DRAWER_BOX, notes="box side, grooved for the bottom"))
    cl.parts.append(Part(
        "Drawer end", 2 * n, length=max(box_w - 2 * bt, 40.0), width=box_h,
        thickness=bt, material=MAT_DRAWER_BOX, notes="box front & back"))
    cl.parts.append(Part(
        "Drawer bottom", n, length=max(box_w - 2 * bt, 40.0),
        width=max(box_depth - bt, 40.0), thickness=bottom_t,
        material=MAT_DRAWER_BOX, grain="width", notes="ply bottom in a groove"))
    cl.hardware.append(Hardware(
        hw.DRAWER_SLIDE.name, n, hw.DRAWER_SLIDE.note, sku=hw.DRAWER_SLIDE.sku,
        category="hardware"))
    if str(pull).strip().lower() != "none":
        cl.hardware.append(Hardware(
            hw.DRAWER_PULL.name, n, f"{pull} pull", sku=hw.DRAWER_PULL.sku,
            category="hardware"))


def _legged_validate_common(spec, issues, dims) -> bool:
    """Shared positive-dimension + leg-fit checks. Returns True if it can continue."""
    def err(f, m):
        issues.append(Issue("error", f, m))

    for name in dims:
        if not _finite_positive(getattr(spec, name)):
            err(name, f"must be a positive, finite number, got {getattr(spec, name)!r}")
    if any(i.severity == "error" for i in issues):
        return False
    if 2 * spec.leg_inset + spec.leg >= min(spec.width, spec.depth):
        err("leg_inset", "legs do not fit within the top with this inset")
        return False
    return True


def _leg_apron_joinery(spec, cl, leg_label="Leg") -> JoineryOp:
    """The leg-to-apron joint op, by joinery family (shared with bench logic)."""
    pid = cl.part_id_for_label
    j = str(spec.joinery).strip().lower()
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
    return JoineryOp(
        part="Leg / apron", operation="leg-to-apron joint", tool=tool,
        width=w, depth=d, reference="apron into leg", part_id=pid(leg_label),
        note=note)


# ===========================================================================
# Nightstand
# ===========================================================================

def _nightstand_drawer_count(spec: NightstandSpec) -> int:
    return max(0, min(int(spec.drawers), 2))


def _nightstand_panels(spec: NightstandSpec) -> list[PanelBox]:
    W, D, H = spec.width, spec.depth, spec.height
    tt, leg = spec.top_thickness, spec.leg
    ah, at = spec.apron_height, spec.apron_thickness
    lx, ly = _legged_offsets(W, D, spec.leg_inset, leg)
    apron_x, apron_y = 2 * lx - leg, 2 * ly - leg
    az = H - tt - ah / 2
    panels: list[PanelBox] = []

    def add(label, size, center, cat, unit="Base"):
        panels.append(PanelBox(label, size, center, cat, subassembly=unit))

    add("Top", (W, D, tt), (0, 0, H - tt / 2), "top", "Top")
    leg_h = H - tt
    for i, sx in enumerate((-1, 1)):
        for j, sy in enumerate((-1, 1)):
            add(f"Leg {2 * i + j + 1}", (leg, leg, leg_h),
                (sx * lx, sy * ly, leg_h / 2), "leg")
    for sx in (-1, 1):
        add("Apron side", (at, apron_y, ah), (sx * lx, 0, az), "apron")
    add("Apron back", (apron_x, at, ah), (0, ly, az), "apron")

    # Front: a top rail above the drawer stack; the drawers hang below it.
    rail_h = 30.0
    add("Front rail", (apron_x, at, rail_h), (0, -ly, H - tt - rail_h / 2), "apron")

    n = _nightstand_drawer_count(spec)
    front_face_y = -(D / 2 - spec.leg_inset)
    dft = 18.0
    fh = spec.drawer_front_height
    gap = 3.0
    zone_top = H - tt - rail_h
    for k in range(n):
        z_center = zone_top - gap - fh / 2 - k * (fh + gap)
        add(f"Drawer front {k + 1}", (apron_x, dft, fh),
            (0, front_face_y + dft / 2, z_center), "drawer", "Drawer")

    if spec.shelf:
        st = spec.shelf_thickness
        add("Shelf", (apron_x, apron_y, st), (0, 0, spec.shelf_setback + st / 2),
            "shelf", "Shelf")
    return panels


def _nightstand_cutlist(spec: NightstandSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    W, D, H = spec.width, spec.depth, spec.height
    lx, ly = _legged_offsets(W, D, spec.leg_inset, spec.leg)
    apron_x, apron_y = 2 * lx - spec.leg, 2 * ly - spec.leg
    leg_h = H - spec.top_thickness

    cl.parts.append(Part(
        "Top", 1, length=W, width=D, thickness=spec.top_thickness,
        material=MAT_TOP, notes="solid or sheet top"))
    cl.parts.append(Part(
        "Leg", 4, length=leg_h, width=spec.leg, thickness=spec.leg,
        material=MAT_LEG, notes="square stock"))
    cl.parts.append(Part(
        "Apron side", 2, length=apron_y, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    cl.parts.append(Part(
        "Apron back", 1, length=apron_x, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    cl.parts.append(Part(
        "Front rail", 1, length=apron_x, width=30.0,
        thickness=spec.apron_thickness, material=MAT_APRON,
        notes="rail above the drawer"))

    n = _nightstand_drawer_count(spec)
    box_depth = max(D - spec.leg_inset - 40.0, 100.0)
    _drawer_cut_parts(cl, n, apron_x, box_depth, spec.drawer_front_height,
                      pull=spec.pull)

    if spec.shelf:
        cl.parts.append(Part(
            "Shelf", 1, length=apron_x, width=apron_y,
            thickness=spec.shelf_thickness, material=MAT_SOLID,
            notes="lower shelf on cleats"))
    cl.hardware.append(Hardware(
        hw.TABLETOP_FASTENER.name, 6, hw.TABLETOP_FASTENER.note,
        sku=hw.TABLETOP_FASTENER.sku, category="fastener"))
    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _nightstand_validate(spec: NightstandSpec) -> list[Issue]:
    issues: list[Issue] = []
    if not _legged_validate_common(
            spec, issues, ("width", "depth", "height", "top_thickness", "leg",
                           "apron_height", "apron_thickness", "leg_inset")):
        return issues

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    if spec.height < 400 or spec.height > 800:
        warn("height", "unusual nightstand height (typically ~500-700mm)")
    n = _nightstand_drawer_count(spec)
    if n:
        stack = n * (spec.drawer_front_height + 3) + 30
        if stack > spec.height - spec.top_thickness:
            warn("drawers",
                 "the drawer stack is taller than the apron zone; reduce the "
                 "drawer count/height or raise the nightstand")
    if spec.shelf and spec.shelf_setback >= spec.height - spec.top_thickness:
        warn("shelf_setback", "the shelf sits above the apron; lower it")
    j = str(spec.joinery).strip().lower()
    if j in ("pocket", "butt", "screw"):
        warn("joinery",
             f"a {j} leg-to-apron joint racks; prefer mortise & tenon or domino")
    return issues


def _nightstand_joinery(spec: NightstandSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops = [_leg_apron_joinery(spec, cl)]
    if _nightstand_drawer_count(spec):
        ops.append(JoineryOp(
            part="Drawer box", operation="groove + slide bore",
            tool="dado / drill", width=6.0, depth=6.0,
            reference="bottom groove; slide screw holes",
            part_id=pid("Drawer side"), note="ball-bearing slides need side clearance"))
    if spec.shelf:
        ops.append(JoineryOp(
            part="Shelf / legs", operation="shelf cleats / dado",
            tool="router / drill", width=round(spec.shelf_thickness, 1), depth=6.0,
            reference="between the legs", part_id=pid("Shelf"),
            note="cleats or a stopped dado carry the shelf"))
    return ops


def _nightstand_assembly(spec: NightstandSpec, cl) -> list[SubAssembly]:
    parts = cl.parts

    def ids(*subs):
        return [p.id for p in parts
                if p.id and any(s in p.name.lower() for s in subs)]

    base_ids = ids("leg", "apron", "front rail", "shelf")
    drawer_ids = ids("drawer")
    top_ids = ids("top")
    hw_names = [h.name for h in cl.hardware]

    base = SubAssembly("Base", "Legs, aprons, front rail, and shelf",
                       part_ids=base_ids, category="carcass")
    base.steps = [
        step(1, "Cut the leg joinery",
              "Mortise the legs and tenon the aprons/rail (or Domino) per the "
              "joinery sheet; add the shelf cleats.", base_ids, category="joinery"),
        step(2, "Glue up the base",
              "Glue the two ends, then the long rails; check for square and wind, "
              "and drop in the shelf.", base_ids, category="carcass"),
    ]
    subs = [base]
    if drawer_ids:
        dr = SubAssembly("Drawer", "Drawer box on slides",
                         part_ids=drawer_ids, category="fronts")
        dr.steps = [
            step(1, "Build & fit the drawer",
                  "Joint the box, groove for the bottom, glue it up square, then "
                  "mount it on its slides and fit the front with an even reveal.",
                  drawer_ids, hw_names, "hardware"),
        ]
        subs.append(dr)
    final = SubAssembly("Top & finish", "Attach the top and finish",
                        part_ids=top_ids, category="final")
    final.steps = [
        step(1, "Attach the top",
              "Fasten the top to the base with figure-8s / Z-clips so a solid top "
              "can move.", top_ids, ["Tabletop fastener"], "hardware"),
        step(2, "Sand & finish", "Final-sand and apply the finish.",
              category="finish"),
    ]
    subs.append(final)
    return subs


furniture.register(
    NIGHTSTAND,
    panels=_nightstand_panels,
    cut_parts=_nightstand_cutlist,
    validate=_nightstand_validate,
    joinery_ops=_nightstand_joinery,
    assembly=_nightstand_assembly,
)


# ===========================================================================
# Desk
# ===========================================================================

def _desk_drawer_count(spec: DeskSpec) -> int:
    return max(0, min(int(spec.drawers), 3))


def _desk_panels(spec: DeskSpec) -> list[PanelBox]:
    W, D, H = spec.width, spec.depth, spec.height
    tt, leg = spec.top_thickness, spec.leg
    ah, at = spec.apron_height, spec.apron_thickness
    lx, ly = _legged_offsets(W, D, spec.leg_inset, leg)
    apron_x, apron_y = 2 * lx - leg, 2 * ly - leg
    az = H - tt - ah / 2
    panels: list[PanelBox] = []

    def add(label, size, center, cat, unit="Base"):
        panels.append(PanelBox(label, size, center, cat, subassembly=unit))

    add("Top", (W, D, tt), (0, 0, H - tt / 2), "top", "Top")
    leg_h = H - tt
    for i, sx in enumerate((-1, 1)):
        for j, sy in enumerate((-1, 1)):
            add(f"Leg {2 * i + j + 1}", (leg, leg, leg_h),
                (sx * lx, sy * ly, leg_h / 2), "leg")
    for sx in (-1, 1):
        add("Apron side", (at, apron_y, ah), (sx * lx, 0, az), "apron")
    add("Apron back", (apron_x, at, ah), (0, ly, az), "apron")

    # Drawers sit side by side across the front, just under the top.
    n = _desk_drawer_count(spec)
    if n == 0:
        add("Apron front", (apron_x, at, ah), (0, -ly, az), "apron")
    else:
        front_face_y = -(D / 2 - spec.leg_inset)
        dft, gap = 18.0, 4.0
        fh = spec.drawer_front_height
        seg = apron_x / n
        for k in range(n):
            cx = -apron_x / 2 + (k + 0.5) * seg
            add(f"Drawer front {k + 1}", (seg - gap, dft, fh),
                (cx, front_face_y + dft / 2, H - tt - gap - fh / 2),
                "drawer", "Drawer")

    if spec.modesty_panel:
        mt = 18.0
        top_z = H - tt - ah
        mz = top_z - spec.modesty_height / 2
        add("Modesty panel", (apron_x, mt, spec.modesty_height),
            (0, ly - at, mz), "carcass", "Modesty")
    return panels


def _desk_cutlist(spec: DeskSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    W, D, H = spec.width, spec.depth, spec.height
    lx, ly = _legged_offsets(W, D, spec.leg_inset, spec.leg)
    apron_x, apron_y = 2 * lx - spec.leg, 2 * ly - spec.leg
    leg_h = H - spec.top_thickness
    n = _desk_drawer_count(spec)

    cl.parts.append(Part(
        "Top", 1, length=W, width=D, thickness=spec.top_thickness,
        material=MAT_TOP, notes="solid or sheet top" +
        ("; bore a cable grommet" if spec.grommet else "")))
    cl.parts.append(Part(
        "Leg", 4, length=leg_h, width=spec.leg, thickness=spec.leg,
        material=MAT_LEG, notes="square stock"))
    cl.parts.append(Part(
        "Apron side", 2, length=apron_y, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    cl.parts.append(Part(
        "Apron back", 1, length=apron_x, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    if n == 0:
        cl.parts.append(Part(
            "Apron front", 1, length=apron_x, width=spec.apron_height,
            thickness=spec.apron_thickness, material=MAT_APRON))
    else:
        seg = apron_x / n
        box_depth = max(D - spec.leg_inset - 40.0, 100.0)
        _drawer_cut_parts(cl, n, seg - 4.0, box_depth, spec.drawer_front_height,
                          pull=spec.pull)
    if spec.modesty_panel:
        cl.parts.append(Part(
            "Modesty panel", 1, length=apron_x, width=spec.modesty_height,
            thickness=18.0, material=MAT_SOLID_PANEL, grain="width",
            notes="back privacy panel"))
    if spec.grommet:
        cl.hardware.append(Hardware(
            hw.DESK_GROMMET.name, 1, f"{spec.grommet_dia:.0f}mm",
            sku=hw.DESK_GROMMET.sku, category="hardware"))
    cl.hardware.append(Hardware(
        hw.TABLETOP_FASTENER.name, 8, hw.TABLETOP_FASTENER.note,
        sku=hw.TABLETOP_FASTENER.sku, category="fastener"))
    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _desk_validate(spec: DeskSpec) -> list[Issue]:
    issues: list[Issue] = []
    if not _legged_validate_common(
            spec, issues, ("width", "depth", "height", "top_thickness", "leg",
                           "apron_height", "apron_thickness", "leg_inset")):
        return issues

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    if spec.height < 680 or spec.height > 800:
        warn("height", "unusual desk height (writing desks are ~720-760mm)")
    n = _desk_drawer_count(spec)
    if n:
        lx, _ = _legged_offsets(spec.width, spec.depth, spec.leg_inset, spec.leg)
        apron_x = 2 * lx - spec.leg
        if apron_x / n < 120:
            warn("drawers",
                 "the drawers are very narrow for this width; use fewer or a wider top")
    if spec.modesty_panel and spec.modesty_height > spec.height - spec.top_thickness - spec.apron_height:
        warn("modesty_height", "the modesty panel is taller than the leg room below the apron")
    j = str(spec.joinery).strip().lower()
    if j in ("pocket", "butt", "screw"):
        warn("joinery",
             f"a {j} leg-to-apron joint racks on a desk; prefer mortise & tenon "
             "or domino")
    return issues


def _desk_joinery(spec: DeskSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops = [_leg_apron_joinery(spec, cl)]
    if _desk_drawer_count(spec):
        ops.append(JoineryOp(
            part="Drawer box", operation="groove + slide bore",
            tool="dado / drill", width=6.0, depth=6.0,
            reference="bottom groove; slide screw holes",
            part_id=pid("Drawer side"), note="full-extension slides for a desk drawer"))
    if spec.grommet:
        ops.append(JoineryOp(
            part="Top", operation="bore cable grommet",
            tool="hole saw / Forstner", width=round(spec.grommet_dia, 1),
            depth=round(spec.top_thickness, 1), reference="rear of the top",
            part_id=pid("Top"), note="fit the grommet ring after finishing"))
    return ops


def _desk_assembly(spec: DeskSpec, cl) -> list[SubAssembly]:
    parts = cl.parts

    def ids(*subs):
        return [p.id for p in parts
                if p.id and any(s in p.name.lower() for s in subs)]

    base_ids = ids("leg", "apron", "modesty")
    drawer_ids = ids("drawer")
    top_ids = ids("top")
    hw_names = [h.name for h in cl.hardware]

    base = SubAssembly("Base", "Legs, aprons, and modesty panel",
                       part_ids=base_ids, category="carcass")
    base.steps = [
        step(1, "Cut the leg joinery",
              "Mortise the legs and tenon the aprons (or Domino); groove for the "
              "modesty panel if used.", base_ids, category="joinery"),
        step(2, "Glue up the base",
              "Glue the ends, then the long aprons with the modesty panel "
              "floating in its grooves; check for square.", base_ids,
              category="carcass"),
    ]
    subs = [base]
    if drawer_ids:
        dr = SubAssembly("Drawers", "Drawer boxes on slides",
                         part_ids=drawer_ids, category="fronts")
        dr.steps = [
            step(1, "Build & hang the drawers",
                  "Build each box, mount it on full-extension slides, and fit the "
                  "fronts with even gaps.", drawer_ids, hw_names, "hardware"),
        ]
        subs.append(dr)
    final = SubAssembly("Top & finish", "Bore the grommet, attach the top, finish",
                        part_ids=top_ids, category="final")
    fsteps = []
    if spec.grommet:
        fsteps.append(step(1, "Bore the cable grommet",
                           "Bore the grommet hole at the rear of the top.",
                           top_ids, category="prep"))
    fsteps.append(step(len(fsteps) + 1, "Attach the top",
                       "Fasten the top with figure-8s / Z-clips for movement.",
                       top_ids, ["Tabletop fastener"], "hardware"))
    fsteps.append(step(len(fsteps) + 1, "Sand & finish",
                       "Final-sand and apply the finish.", category="finish"))
    final.steps = fsteps
    subs.append(final)
    return subs


furniture.register(
    DESK,
    panels=_desk_panels,
    cut_parts=_desk_cutlist,
    validate=_desk_validate,
    joinery_ops=_desk_joinery,
    assembly=_desk_assembly,
)


# ===========================================================================
# Workbench
# ===========================================================================

def _workbench_panels(spec: WorkbenchSpec) -> list[PanelBox]:
    W, D, H = spec.width, spec.depth, spec.height
    tt, leg = spec.top_thickness, spec.leg
    ah, at = spec.apron_height, spec.apron_thickness
    lx, ly = _legged_offsets(W, D, spec.leg_inset, leg)
    apron_x, apron_y = 2 * lx - leg, 2 * ly - leg
    az = H - tt - ah / 2
    panels: list[PanelBox] = []

    def add(label, size, center, cat, unit="Base"):
        panels.append(PanelBox(label, size, center, cat, subassembly=unit))

    add("Top", (W, D, tt), (0, 0, H - tt / 2), "top", "Top")
    leg_h = H - tt
    for i, sx in enumerate((-1, 1)):
        for j, sy in enumerate((-1, 1)):
            add(f"Leg {2 * i + j + 1}", (leg, leg, leg_h),
                (sx * lx, sy * ly, leg_h / 2), "leg")
    for sx in (-1, 1):
        add("Apron side", (at, apron_y, ah), (sx * lx, 0, az), "apron")
    for sy in (-1, 1):
        add("Apron long", (apron_x, at, ah), (0, sy * ly, az), "apron")

    if spec.stretchers:
        sh, st = spec.stretcher_height, spec.stretcher_thickness
        sz = spec.stretcher_setback
        for sy in (-1, 1):
            add("Stretcher", (apron_x, st, sh), (0, sy * ly, sz), "stretcher",
                "Stretchers")
        if spec.shelf:
            add("Shelf", (apron_x, apron_y, spec.shelf_thickness),
                (0, 0, sz + sh / 2 + spec.shelf_thickness / 2), "shelf", "Shelf")
    # The vise jaw is a small bolt-on part — kept in the cut list + joinery, not
    # the geometry, so it never distorts the bench envelope or clashes an apron.
    return panels


def _workbench_cutlist(spec: WorkbenchSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    W, D, H = spec.width, spec.depth, spec.height
    lx, ly = _legged_offsets(W, D, spec.leg_inset, spec.leg)
    apron_x, apron_y = 2 * lx - spec.leg, 2 * ly - spec.leg
    leg_h = H - spec.top_thickness

    cl.parts.append(Part(
        "Top lamination", spec.lamination_count, length=W, width=spec.top_thickness,
        thickness=max(spec.depth / spec.lamination_count, 25.0), material=MAT_SOLID,
        grain="length",
        notes=f"laminate {spec.lamination_count} strips on edge into the {spec.top_thickness:.0f}mm top"))
    cl.parts.append(Part(
        "Leg", 4, length=leg_h, width=spec.leg, thickness=spec.leg,
        material=MAT_LEG, notes="heavy square stock"))
    cl.parts.append(Part(
        "Apron long", 2, length=apron_x, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    cl.parts.append(Part(
        "Apron side", 2, length=apron_y, width=spec.apron_height,
        thickness=spec.apron_thickness, material=MAT_APRON))
    if spec.stretchers:
        cl.parts.append(Part(
            "Stretcher", 2, length=apron_x, width=spec.stretcher_height,
            thickness=spec.stretcher_thickness, material=MAT_APRON,
            notes="lower rail, draw-bored"))
        if spec.shelf:
            cl.parts.append(Part(
                "Shelf", 1, length=apron_x, width=apron_y,
                thickness=spec.shelf_thickness, material=MAT_SOLID,
                notes="tool shelf on the stretchers"))
    if str(spec.vise_side).strip().lower() in ("left", "right", "front"):
        cl.parts.append(Part(
            "Vise jaw", 1, length=min(250.0, W * 0.3), width=spec.apron_height,
            thickness=spec.apron_thickness, material=MAT_SOLID,
            notes="wooden jaw faced onto the vise"))

    if spec.vise:
        cl.hardware.append(Hardware(
            hw.BENCH_VISE.name, 1, f"{spec.vise_side} vise", sku=hw.BENCH_VISE.sku,
            category="hardware"))
    cl.hardware.append(Hardware(
        hw.BENCH_DOG.name, max(2, spec.dog_hole_count // 2), hw.BENCH_DOG.note,
        sku=hw.BENCH_DOG.sku, category="hardware"))
    cl.hardware.append(Hardware(
        hw.LEG_BRACKET.name, 4, "draw-bore pins / bolts", sku=hw.LEG_BRACKET.sku,
        category="fastener"))
    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _workbench_validate(spec: WorkbenchSpec) -> list[Issue]:
    issues: list[Issue] = []
    if not _legged_validate_common(
            spec, issues, ("width", "depth", "height", "top_thickness", "leg",
                           "apron_height", "apron_thickness", "leg_inset")):
        return issues

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    if spec.height < 800 or spec.height > 1000:
        warn("height", "unusual bench height (typically ~850-950mm; near hip)")
    if spec.top_thickness < 50:
        warn("top_thickness",
             "a workbench top under ~50mm flexes and dents; laminate it thicker")
    if not spec.stretchers:
        warn("stretchers",
             "a bench without stretchers racks under planing; add lower rails")
    j = str(spec.joinery).strip().lower()
    if j in ("pocket", "butt", "screw", "dowel"):
        warn("joinery",
             f"a {j} base joint racks under bench loads; use draw-bored mortise & "
             "tenon")
    if str(spec.vise_side).strip().lower() not in ("left", "right", "front", "none"):
        warn("vise_side", "vise_side should be left, right, front, or none")
    return issues


def _workbench_joinery(spec: WorkbenchSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops = [JoineryOp(
        part="Leg / apron", operation="draw-bored mortise & tenon",
        tool="mortiser / saw + drawbore pins", width=round(spec.apron_thickness / 3, 1),
        depth=round(spec.leg * 0.7, 1), reference="aprons & stretchers into legs",
        part_id=pid("Leg"), note="offset-bored pins pull the joints tight without clamps")]
    ops.append(JoineryOp(
        part="Top", operation=f"bore {spec.dog_hole_count} dog holes",
        tool=f"{spec.dog_hole_dia:.0f}mm auger / Forstner", width=round(spec.dog_hole_dia, 1),
        depth=round(spec.top_thickness, 1), reference="a row along the front edge",
        part_id=pid("Top lamination"),
        note="space ~150mm; align with the vise for clamping with dogs"))
    if str(spec.vise_side).strip().lower() in ("left", "right", "front"):
        ops.append(JoineryOp(
            part="Top / leg", operation="mount the vise",
            tool="drill / driver", width=0.0, depth=round(spec.top_thickness, 1),
            reference=f"{spec.vise_side} corner under the top", part_id=pid("Vise jaw"),
            note="face the metal vise with a wooden jaw flush to the benchtop"))
    return ops


def _workbench_assembly(spec: WorkbenchSpec, cl) -> list[SubAssembly]:
    parts = cl.parts

    def ids(*subs):
        return [p.id for p in parts
                if p.id and any(s in p.name.lower() for s in subs)]

    top_ids = ids("top lamination")
    base_ids = ids("leg", "apron", "stretcher", "shelf")
    vise_ids = ids("vise")
    hw_names = [h.name for h in cl.hardware]

    top = SubAssembly("Top", "The thick laminated benchtop",
                      part_ids=top_ids, category="carcass")
    top.steps = [
        step(1, "Laminate the top",
              "Glue the strips on edge in stages, flatten the slab, then bore the "
              "dog-hole row aligned to the vise.", top_ids, category="carcass"),
    ]
    base = SubAssembly("Base", "Legs, aprons, stretchers, and shelf",
                       part_ids=base_ids, category="carcass")
    base.steps = [
        step(1, "Cut the base joinery",
              "Mortise the legs and tenon the aprons and stretchers; drawbore the "
              "pin holes offset for a tight pull.", base_ids, category="joinery"),
        step(2, "Assemble the base",
              "Glue and drawbore the two ends, then join with the long rails; "
              "check for square and add the tool shelf.", base_ids, category="carcass"),
    ]
    final = SubAssembly("Mount & finish", "Join top to base, fit the vise, finish",
                        part_ids=vise_ids, category="final")
    final.steps = [
        step(1, "Attach the top",
              "Fasten the slab to the base (lag bolts in slotted holes for "
              "movement).", top_ids, ["Leg-to-apron bracket"], "hardware"),
        step(2, "Fit the vise & dogs",
              "Mount the vise, fit and trim its wooden jaw flush, and drop in the "
              "bench dogs.", vise_ids, hw_names, "hardware"),
        step(3, "Finish",
              "A wiping oil/varnish finish — easy to renew and won't make the top "
              "slick.", category="finish"),
    ]
    return [top, base, final]


furniture.register(
    WORKBENCH,
    panels=_workbench_panels,
    cut_parts=_workbench_cutlist,
    validate=_workbench_validate,
    joinery_ops=_workbench_joinery,
    assembly=_workbench_assembly,
)
