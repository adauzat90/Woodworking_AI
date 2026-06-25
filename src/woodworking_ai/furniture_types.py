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

No CAD dependency.
"""

from __future__ import annotations

import math

from . import furniture
from .dispatch import WALL_SHELF, BOX, BENCH
from .dsl import WallShelfSpec, BoxSpec, BenchSpec, ShelfFixing, CornerJoint
from .geometry import PanelBox
from .cutlist import CutList, Part, Hardware, assign_ids, _resolve_part_stock
from .validator import Issue
from .joinery import JoineryOp
from .assembly_steps import SubAssembly, _step
from . import engineering
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
        material="solid", grain="length", notes="shelf board"))

    fixing = spec.fixing
    if fixing == ShelfFixing.FRENCH_CLEAT:
        ch = spec.cleat_height
        cl.parts.append(Part(
            "Cleat", 2, length=L, width=ch, thickness=t, material="solid",
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

    _resolve_part_stock(cl.parts, spec)
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
        _step(1, "Mill & finish the board",
              "Dimension the shelf board (and cleats), ease the edges, and apply "
              "the finish before mounting.", ids, category="prep"),
    ]
    if spec.fixing == ShelfFixing.FRENCH_CLEAT:
        sub.steps.append(_step(
            2, "Cut & fit the French cleat",
            "Rip the 45° bevel pair; fix the wall strip level into studs and "
            "screw the shelf strip under the board's rear.", ids, hw_names,
            "hardware"))
        sub.steps.append(_step(
            3, "Hang the shelf",
            "Drop the board's cleat onto the wall cleat — it self-registers and "
            "locks down.", category="hardware"))
    elif spec.fixing == ShelfFixing.BRACKETS:
        sub.steps.append(_step(
            2, "Mount the brackets & shelf",
            "Anchor the brackets level into studs, then screw the board down to "
            "them.", ids, hw_names, "hardware"))
    else:
        sub.steps.append(_step(
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
        "Front/back", 2, length=W, width=bh - t, thickness=t, material="solid",
        grain="length", notes=f"{cj} corners"))
    cl.parts.append(Part(
        "Side", 2, length=D - 2 * t, width=bh - t, thickness=t, material="solid",
        grain="length", notes=f"{cj} corners"))
    cl.parts.append(Part(
        "Bottom", 1, length=W - 2 * t, width=D - 2 * t, thickness=t,
        material="solid", grain="length", notes="captured in a groove"))
    if spec.lid:
        cl.parts.append(Part(
            "Lid", 1, length=W, width=D, thickness=t, material="solid",
            grain="length", notes="hinged lid"))
        n = max(spec.hinges, 2)
        cl.hardware.append(Hardware(
            hw.BUTT_HINGE.name, n, hw.BUTT_HINGE.note, sku=hw.BUTT_HINGE.sku,
            category="hardware"))
        cl.hardware.append(Hardware(
            hw.LID_SUPPORT.name, 1, hw.LID_SUPPORT.note, sku=hw.LID_SUPPORT.sku,
            category="hardware"))

    _resolve_part_stock(cl.parts, spec)
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
        _step(1, "Cut the corner joints & bottom groove",
              "Cut the chosen corner joint on all four corners and the groove "
              "for the bottom per the joinery sheet.", body_ids, category="joinery"),
        _step(2, "Glue up the box",
              "Dry-fit, then glue and clamp the box square; slide the bottom into "
              "its groove and check it is flat and not in wind.", body_ids,
              category="carcass"),
    ]
    subs = [body]
    if spec.lid:
        lid = SubAssembly("Lid", "A hinged lid", part_ids=lid_ids,
                          category="fronts")
        lid.steps = [
            _step(1, "Fit & hinge the lid",
                  "Trim the lid to fit, mortise the hinges into the lid and rear, "
                  "and hang it; add the lid stay.", lid_ids, hw_names, "hardware"),
        ]
        subs.append(lid)
    final = SubAssembly("Final", "Finish the chest", category="final")
    final.steps = [
        _step(1, "Sand & finish",
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
    ah, at, li = spec.apron_height, spec.apron_thickness, spec.leg_inset
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
        thickness=spec.top_thickness, material="top", notes="solid/sheet seat"))
    cl.parts.append(Part(
        "Leg", 4, length=leg_h, width=spec.leg, thickness=spec.leg,
        material="leg", notes="square stock"))
    cl.parts.append(Part(
        "Apron (long)", 2, length=apron_x, width=spec.apron_height,
        thickness=spec.apron_thickness, material="apron"))
    cl.parts.append(Part(
        "Apron (short)", 2, length=apron_y, width=spec.apron_height,
        thickness=spec.apron_thickness, material="apron"))
    if spec.stretchers:
        cl.parts.append(Part(
            "Stretcher", 2, length=apron_x, width=spec.stretcher_height,
            thickness=spec.stretcher_thickness, material="apron",
            notes="lower rail, resists racking"))
    cl.hardware.append(Hardware("Corner bracket", 4, "leg-to-apron"))
    cl.hardware.append(Hardware("Seat fastener", 6, "expansion clip"))
    _resolve_part_stock(cl.parts, spec)
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
        _step(1, "Cut the leg joints",
              "Mortise the legs and tenon the aprons and stretchers (or Domino/"
              "dowel) per the joinery sheet.", base_ids, category="joinery"),
        _step(2, "Glue up the base",
              "Glue the two end assemblies (legs + short aprons + stretchers), "
              "then join with the long rails; check for square and wind.",
              base_ids, category="carcass"),
    ]
    seat_sub = SubAssembly("Seat", "The seat top", part_ids=seat,
                           category="carcass")
    seat_sub.steps = [
        _step(1, "Prepare the seat",
              "Edge-glue the boards into a flat panel (or dimension the sheet) "
              "and sand level.", seat, category="carcass"),
    ]
    final = SubAssembly("Final assembly", "Join seat to base and finish",
                        category="final")
    final.steps = [
        _step(1, "Attach the seat",
              "Fasten the seat to the base allowing for seasonal movement "
              "(figure-8 fasteners / Z-clips).", seat, ["Seat fastener"],
              "hardware"),
        _step(2, "Sand & finish", "Final-sand and apply the finish.",
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
