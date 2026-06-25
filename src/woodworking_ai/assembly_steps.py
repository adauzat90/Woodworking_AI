"""Assembly plan: break the piece into sub-assemblies, then build each.

A shop doesn't build a cabinet in one flat list of steps — it builds the
*sub-assemblies* (the carcass, each drawer box, each door, the face frame),
then brings them together. This module mirrors that: it decomposes the spec
into :class:`SubAssembly` units, each with the parts it owns and the ordered
steps to build *that* unit, finishing with a "Final assembly" that joins them.

Each step names the part IDs and hardware it touches, so the package
cross-references the cut list, drilling, and joinery. Pure logic — no CAD.
A flat :func:`assembly_sequence` is still provided (it flattens the plan) for
callers that want one numbered checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import (CabinetSpec, TableSpec, Construction)
from .dispatch import spec_kind, VOID, GROUP, TABLE, CABINET
from . import furniture
from .cutlist import generate_cutlist
from .geometry import component_tag


# --- glue-up / clamping guidance (H4) ---------------------------------------
# A glued joint wants ~1 clamp every 150-200mm of glue line and clamps long
# enough to span what's being closed. Below that the clamp pressure cones leave
# starved gaps between clamps; above it you're just buying clamps.
CLAMP_SPACING_MM = 175.0      # nominal clamp spacing along the glue line
PVA_OPEN_TIME_MIN = (5, 10)   # working/open time of ordinary PVA before tack


def clamp_plan(glue_line_mm: float, span_mm: float,
               spacing_mm: float = CLAMP_SPACING_MM) -> dict:
    """Clamp schedule for one glue-up: count + nominal clamp length.

    *glue_line_mm* is the length of joint being closed (sets the **count**, ~1
    clamp per ``spacing_mm``); *span_mm* is the distance the clamps must reach
    across (sets the **length** — round up ~100mm of working slack). Returns
    ``{count, length_mm, spacing_mm}``; an empty/zero glue-up yields no clamps.
    """
    glue_line = max(float(glue_line_mm or 0.0), 0.0)
    span = max(float(span_mm or 0.0), 0.0)
    if glue_line <= 0 or span <= 0:
        return {"count": 0, "length_mm": 0.0, "spacing_mm": spacing_mm}
    import math
    count = max(2, math.ceil(glue_line / spacing_mm) + 1)
    # Real clamps come in nominal lengths; round the reach up to a sensible 50mm.
    length = math.ceil((span + 100.0) / 50.0) * 50.0
    return {"count": count, "length_mm": float(length), "spacing_mm": spacing_mm}


def _span_of(parts_by_id: dict, ids) -> tuple[float, float]:
    """``(glue_line, span)`` mm from the parts in *ids*.

    Glue line ≈ the longest part dimension involved (the run being glued); span
    ≈ the largest cross-measure the clamps must close (the second dimension).
    """
    longs: list[float] = []
    shorts: list[float] = []
    for pid in ids or ():
        p = parts_by_id.get(pid)
        if p is None:
            continue
        longs.append(max(p.length, p.width))
        shorts.append(min(p.length, p.width))
    if not longs:
        return 0.0, 0.0
    return max(longs), max(shorts)


def _clamp_step(n, parts_by_id, ids, category="carcass",
                title="Clamp schedule"):
    """Build an AssemblyStep describing the clamp plan for *ids* (or None)."""
    glue_line, span = _span_of(parts_by_id, ids)
    plan = clamp_plan(glue_line, span)
    if plan["count"] <= 0:
        return None
    detail = (f"Use ~{plan['count']} clamps (about 1 per "
              f"{int(plan['spacing_mm'])}mm of glue line), each at least "
              f"~{int(plan['length_mm'])}mm long to span the joint. "
              "Alternate clamps over and under to keep the panel flat.")
    return _step(n, title, detail, list(ids or []), ["Bar/parallel clamps"],
                 category)


@dataclass
class AssemblyStep:
    number: int
    title: str
    detail: str
    part_ids: list[str] = field(default_factory=list)
    hardware: list[str] = field(default_factory=list)
    category: str = "assembly"   # prep | joinery | carcass | fronts | hardware | finish


@dataclass
class SubAssembly:
    """One buildable unit (carcass, a drawer box, a door, ...) and its steps."""
    name: str
    detail: str
    steps: list[AssemblyStep] = field(default_factory=list)
    part_ids: list[str] = field(default_factory=list)
    category: str = "subassembly"


@dataclass
class AssemblyPlan:
    spec_name: str
    subassemblies: list[SubAssembly] = field(default_factory=list)

    def flat_steps(self) -> list[AssemblyStep]:
        """Every step across all sub-assemblies, renumbered 1..N."""
        out: list[AssemblyStep] = []
        for sub in self.subassemblies:
            for s in sub.steps:
                out.append(AssemblyStep(
                    len(out) + 1, s.title, s.detail, s.part_ids, s.hardware,
                    s.category))
        return out

    def report_text(self) -> str:
        lines = [f"Build plan — {self.spec_name} "
                 f"({len(self.subassemblies)} sub-assemblies)"]
        for sub in self.subassemblies:
            ids = f"  [{', '.join(sub.part_ids)}]" if sub.part_ids else ""
            lines.append(f"\n■ {sub.name} — {sub.detail}{ids}")
            for s in sub.steps:
                lines.append(f"    {s.number}. {s.title}: {s.detail}")
                if s.hardware:
                    lines.append(f"         hardware: {', '.join(s.hardware)}")
        return "\n".join(lines)


# Backwards-compatible flat sequence -----------------------------------------

@dataclass
class AssemblySequence:
    spec_name: str
    steps: list[AssemblyStep] = field(default_factory=list)

    def report_text(self) -> str:
        lines = [f"Assembly sequence — {self.spec_name} ({len(self.steps)} steps)"]
        for s in self.steps:
            ids = f"  [{', '.join(s.part_ids)}]" if s.part_ids else ""
            lines.append(f"  {s.number}. {s.title}: {s.detail}{ids}")
            if s.hardware:
                lines.append(f"       hardware: {', '.join(s.hardware)}")
        return "\n".join(lines)


def _ids(parts, *predicates) -> list[str]:
    """IDs of parts whose name matches any of the *predicates* (substrings)."""
    out = []
    for p in parts:
        n = p.name.lower()
        if any(pred in n for pred in predicates) and p.id:
            out.append(p.id)
    return out


def _step(n, title, detail, part_ids=None, hardware=None, category="assembly"):
    return AssemblyStep(n, title, detail, part_ids or [], hardware or [], category)


def _renumber(steps: list["AssemblyStep"]) -> None:
    """Renumber *steps* 1..N in place (after we splice extra steps in)."""
    for i, s in enumerate(steps, start=1):
        s.number = i


def _augment_glue_up(sub: "SubAssembly", parts_by_id: dict, glue_ids,
                     category: str = "carcass", *, cross_grain: bool = False,
                     float_panel: bool = False) -> None:
    """Add dry-fit, square-check, open-time and clamp-schedule steps to *sub*.

    Additive: the unit's existing glue step is kept; these augment it. The new
    steps are appended and the whole unit is renumbered. *glue_ids* drive the
    clamp plan (and are referenced by the steps). ``cross_grain`` surfaces the
    don't-glue-wide-panels-rigidly caution; ``float_panel`` is set for a
    frame-around-a-floating-panel glue-up (door leaf) so the caution fits.
    """
    if not sub.steps:
        return
    ids = list(glue_ids or [])
    extra: list[AssemblyStep] = []
    n0 = len(sub.steps)
    extra.append(_step(
        n0 + 1, "Dry-fit before glue",
        "Assemble dry with clamps and a square: confirm every joint closes and "
        "nothing racks before any glue is spread.", ids, category=category))
    extra.append(_step(
        n0 + 2, "Glue open-time caution",
        f"Ordinary PVA has only ~{PVA_OPEN_TIME_MIN[0]}-{PVA_OPEN_TIME_MIN[1]} "
        "min of open time — lay clamps and cauls out first, and use a slower "
        "glue for a big glue-up.", ids, category=category))
    extra.append(_step(
        n0 + 3, "Check diagonals for square",
        "With the joint clamped, measure both diagonals: equal means square. "
        "Adjust clamp angle until they match, then leave it to cure.", ids,
        category=category))
    clamp = _clamp_step(n0 + 4, parts_by_id, ids, category=category)
    if clamp is not None:
        extra.append(clamp)
    if cross_grain:
        extra.append(_step(
            n0 + 5, "Cross-grain caution",
            "Don't glue a wide solid panel rigidly cross-grain — it will move "
            "with the seasons and split. Let wide panels float, or fasten with "
            "slotted/expansion hardware.", ids, category=category))
    elif float_panel:
        extra.append(_step(
            n0 + 5, "Leave the panel floating",
            "Glue the frame corners only — leave the centre panel floating in "
            "its groove so it can move cross-grain without splitting the frame.",
            ids, category=category))
    sub.steps.extend(extra)
    _renumber(sub.steps)


def _classify_parts(parts) -> dict[str, list[str]]:
    """Group cut-list part IDs into the sub-assemblies that build them.

    Precise, material-aware grouping: drawer-box and door parts are claimed by
    their own sub-assemblies, so the carcass is what's left of the sheet goods
    (sides/bottom/top/stretcher) — never a "box side" or a "countertop".
    """
    def ids_where(pred) -> list[str]:
        return [p.id for p in parts if p.id and pred(p)]

    def name_has(p, *subs) -> bool:
        n = p.name.lower()
        return any(s in n for s in subs)

    groups = {
        "drawer_box": ids_where(lambda p: p.material == "drawer box"
                                or (name_has(p, "drawer") and name_has(p, "box"))),
        "door": ids_where(lambda p: p.material in ("door/front", "door panel")
                          and name_has(p, "door")),
        "frame": ids_where(lambda p: p.material == "frame"),
        "accessory": ids_where(lambda p: p.material in ("countertop", "molding")
                               or name_has(p, "filler", "end panel")),
        "shelves": ids_where(lambda p: name_has(p, "shelf")),
        "toe": ids_where(lambda p: name_has(p, "toe")),
        "back": ids_where(lambda p: p.material == "back panel"
                          and not name_has(p, "drawer")),
        "sides": ids_where(lambda p: p.material == "sheet" and name_has(p, "side")
                           and not name_has(p, "drawer")),
    }
    claimed = set(groups["drawer_box"] + groups["door"] + groups["frame"]
                  + groups["accessory"] + groups["shelves"] + groups["toe"]
                  + groups["back"])
    # Carcass: the structural box panels not claimed by another sub-assembly.
    groups["carcass"] = ids_where(
        lambda p: p.id not in claimed
        and p.material in ("sheet", "solid panel")
        and not name_has(p, "drawer front"))
    return groups


def _cabinet_plan(spec: CabinetSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    by_id = {p.id: p for p in parts if p.id}
    all_ids = [p.id for p in parts if p.id]
    g = _classify_parts(parts)
    door_parts = g["door"]
    frame = g["frame"]
    shelves = g["shelves"]
    toe = g["toe"]
    back = g["back"]
    sides = g["sides"]
    carcass = g["carcass"]
    hw = {h.name for h in cl.hardware}
    is_ff = spec.construction == Construction.FACE_FRAME
    style = str(getattr(spec, "door_style", "slab")).lower()
    subs: list[SubAssembly] = []

    # --- preparation (shared) -------------------------------------------
    prep = SubAssembly("Preparation", "Mill and drill every part before glue-up",
                       part_ids=all_ids, category="prep")
    prep.steps = [
        _step(1, "Mill & label all parts",
              "Cut every panel to the cut-list sizes and label each with its ID; "
              "check the grain runs as marked.", all_ids, category="prep"),
        _step(2, "Drill the flat panels first",
              "Bore the 32mm shelf-pin lines, hinge cups and slide/plate holes "
              "while the panels are flat — before any assembly.",
              sorted(set(sides + door_parts)),
              [h for h in ("Shelf pin", "Concealed hinge") if h in hw], "prep"),
    ]
    subs.append(prep)

    # --- carcass --------------------------------------------------------
    carc = SubAssembly("Carcass", "The box: sides, bottom, top/stretchers, back",
                       part_ids=sorted(set(carcass + back + toe)), category="carcass")
    carc.steps = [
        _step(1, "Cut the carcass joinery",
              "Run the dados/rabbets and the back housing per the joinery sheet; "
              "dry-fit and check for square.", sides, category="joinery"),
        _step(2, "Glue & clamp the carcass",
              "Assemble the bottom and top/stretchers between the sides, glue and "
              "clamp, and check the diagonals are equal.", carcass,
              category="carcass"),
    ]
    if back:
        carc.steps.append(_step(
            len(carc.steps) + 1, "Fit the back",
            "Seat the back in its rabbet/groove (or apply it) to square and "
            "stiffen the box.", back, ["Back panel screw 4×16"], "carcass"))
    if toe:
        carc.steps.append(_step(
            len(carc.steps) + 1, "Attach the toe kick",
            "Fix the toe kick to the cabinet base.", toe, category="carcass"))
    # A solid-wood (edge-glued) carcass has wide cross-grain panels to watch.
    carc_cross_grain = any(by_id[i].material in ("solid panel", "solid")
                           for i in carcass if i in by_id)
    _augment_glue_up(carc, by_id, sorted(set(carcass + back)),
                     category="carcass", cross_grain=carc_cross_grain)
    subs.append(carc)

    # --- face frame (its own sub-assembly) ------------------------------
    if is_ff and frame:
        ff = SubAssembly("Face frame", "Solid stiles and rails over the carcass "
                         "front", part_ids=frame, category="carcass")
        ff.steps = [
            _step(1, "Join the frame",
                  "Pocket-screw or Domino the stiles and rails into a flat frame; "
                  "check it sits square.", frame, category="joinery"),
            _step(2, "Attach to the carcass",
                  "Glue/screw the frame to the carcass front and flush-trim the "
                  "overhang.", frame, category="carcass"),
        ]
        _augment_glue_up(ff, by_id, frame, category="carcass")
        subs.append(ff)

    # --- one sub-assembly per drawer box --------------------------------
    boxed = [(i, d) for i, d in enumerate(spec.drawers, start=1)
             if not d.false_front]
    for i, _d in boxed:
        box_ids = _ids(parts, f"drawer {i} box")
        sub = SubAssembly(f"Drawer box {i}", "Four sides and a captured bottom",
                          part_ids=box_ids, category="drawer")
        sub.steps = [
            _step(1, "Cut the corner joints & bottom groove",
                  "Cut the drawer-corner joint and the groove for the bottom per "
                  "the joinery sheet.", box_ids, category="joinery"),
            _step(2, "Glue up the box",
                  "Glue and clamp the box square, slide the bottom into its "
                  "groove, and check it is flat and not in wind.", box_ids,
                  category="drawer"),
        ]
        _augment_glue_up(sub, by_id, box_ids, category="drawer")
        subs.append(sub)

    # --- one sub-assembly per 5-piece door leaf -------------------------
    if style != "slab" and door_parts:
        leaves = [("", "the door")] if spec.doors == 1 else [
            ("L", "the left door"), ("R", "the right door")]
        for hand, label in leaves[:max(spec.doors, 0)]:
            suf = f" {hand}" if hand else ""
            leaf_ids = _ids(parts, "door stile", "door rail", "door panel")
            sub = SubAssembly(f"Door{suf or ' (single)'}",
                              "Five-piece frame around a floating panel",
                              part_ids=leaf_ids, category="door")
            sub.steps = [
                _step(1, "Cope-and-stick the frame",
                      "Stick the inner edges of the stiles and rails and cope the "
                      "rail ends to match; cut the panel groove.", leaf_ids,
                      category="joinery"),
                _step(2, "Glue the frame around the panel",
                      "Dry-fit, then glue the frame corners only — leave the panel "
                      "floating so it can move — and clamp flat.", leaf_ids,
                      category="door"),
            ]
            _augment_glue_up(sub, by_id, leaf_ids, category="door",
                             float_panel=True)
            subs.append(sub)

    # --- final assembly: bring the sub-assemblies together --------------
    final = SubAssembly("Final assembly", "Fit the sub-assemblies and finish",
                        category="final")
    n = 0

    def fstep(title, detail, ids=None, hardware=None, category="fronts"):
        nonlocal n
        n += 1
        final.steps.append(_step(n, title, detail, ids or [], hardware or [],
                                 category))

    if boxed:
        fstep("Mount slides & fit the drawer boxes",
              "Install the slides in the cabinet and fit each drawer box; adjust "
              "for even reveals.", _ids(parts, "box"),
              [h for h in hw if "slide" in h.lower()], "fronts")
    if any("drawer front" in p.name.lower() for p in parts):
        fstep("Fit the drawer fronts",
              "Attach the drawer fronts to the boxes and set consistent gaps.",
              _ids(parts, "drawer front"),
              [h for h in hw if "drawer pull" in h.lower()])
    if door_parts:
        fstep("Hang the doors",
              "Mount the hinges and plates, hang each door, and adjust the "
              "three-way for even reveals.", door_parts,
              [h for h in hw if "hinge" in h.lower() or "plate" in h.lower()])
    fstep("Install hardware & shelves",
          "Fit pulls, shelf pins and adjustable shelves.", shelves,
          [h for h in hw if "pull" in h.lower() or "pin" in h.lower()], "hardware")
    acc_ids = _ids(parts, "countertop", "filler", "end panel", "molding")
    if acc_ids:
        fstep("Fit the trim & countertop",
              "Scribe and fit the fillers/end panels, set the countertop, and "
              "install any moldings.", acc_ids, category="hardware")
    fstep("Sand & finish",
          "Final-sand, ease the edges, and apply the finish schedule.",
          category="finish")
    subs.append(final)
    return subs


def _table_plan(spec: TableSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    by_id = {p.id: p for p in parts if p.id}
    legs = _ids(parts, "leg")
    aprons = _ids(parts, "apron")
    top = _ids(parts, "top")
    base = SubAssembly("Base", "Four legs joined by aprons",
                       part_ids=sorted(set(legs + aprons)), category="carcass")
    base.steps = [
        _step(1, "Cut the leg-to-apron joints",
              "Mortise the legs and tenon the aprons (or Domino/dowel) per the "
              "joinery sheet.", legs + aprons, category="joinery"),
        _step(2, "Glue up the base",
              "Glue the two end assemblies, then join with the long aprons; check "
              "for square and wind.", legs + aprons, category="carcass"),
    ]
    _augment_glue_up(base, by_id, legs + aprons, category="carcass")
    top_sub = SubAssembly("Top", "The tabletop", part_ids=top, category="carcass")
    top_sub.steps = [
        _step(1, "Prepare the top",
              "Edge-glue the boards into a flat panel (or dimension the sheet) and "
              "sand level.", top, category="carcass"),
    ]
    # A solid edge-glued top is the canonical wide cross-grain panel.
    top_cross_grain = any(by_id[i].material in ("top", "solid panel", "solid")
                          for i in top if i in by_id)
    _augment_glue_up(top_sub, by_id, top, category="carcass",
                     cross_grain=top_cross_grain)
    final = SubAssembly("Final assembly", "Join top to base and finish",
                        category="final")
    final.steps = [
        _step(1, "Attach the top",
              "Fasten the top to the base with a method that allows seasonal "
              "movement (figure-8 fasteners / Z-clips).", top,
              ["Tabletop fastener"], "hardware"),
        _step(2, "Sand & finish", "Final-sand and apply the finish.",
              category="finish"),
    ]
    return [base, top_sub, final]


def assembly_plan(spec) -> AssemblyPlan:
    """Decompose *spec* into sub-assemblies, each with its own build steps."""
    kind = spec_kind(spec)
    if kind == VOID:
        return AssemblyPlan(spec.name)   # a reserved gap is built by nobody
    if kind == GROUP:
        plan = AssemblyPlan(spec.name)
        for i, comp in enumerate(spec.components, start=1):
            tag = component_tag(comp, i)
            for sub in assembly_plan(comp.spec).subassemblies:
                plan.subassemblies.append(SubAssembly(
                    name=f"[{tag}] {sub.name}", detail=sub.detail,
                    part_ids=[f"{tag}-{pid}" for pid in sub.part_ids],
                    category=sub.category,
                    steps=[_step(s.number, s.title, s.detail,
                                 [f"{tag}-{pid}" for pid in s.part_ids],
                                 s.hardware, s.category) for s in sub.steps]))
        run = SubAssembly("Set & join the run",
                          "Install the cabinets as a run", category="install")
        run.steps = [
            _step(1, "Set & level the cabinets",
                  "Level each cabinet, shim to the floor, and clamp the faces "
                  "flush.", category="install"),
            _step(2, "Join & scribe",
                  "Screw the cabinets together and scribe the end panels/fillers "
                  "to the walls.", category="install"),
        ]
        plan.subassemblies.append(run)
        return plan
    cl = generate_cutlist(spec)
    # Every leaf type contributes its sub-assemblies through the furniture
    # registry; a new type adds a build plan by registering ``assembly`` (or
    # falls back to a generic one-unit plan).
    return AssemblyPlan(spec.name, furniture.get(kind).assembly(spec, cl))


def assembly_sequence(spec) -> AssemblySequence:
    """Flat, numbered build checklist (flattens :func:`assembly_plan`)."""
    plan = assembly_plan(spec)
    return AssemblySequence(plan.spec_name, plan.flat_steps())


# Register the built-in leaf build plans. A new furniture type registers its own
# ``assembly`` in its home module (or omits it for a generic one-unit plan).
furniture.register(CABINET, assembly=_cabinet_plan)
furniture.register(TABLE, assembly=_table_plan)
