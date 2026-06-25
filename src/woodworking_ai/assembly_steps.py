"""Assembly sequence: the ordered steps to build the piece.

A cut list and a 3D model are not a build plan. This module derives an ordered
sequence of :class:`AssemblyStep` from the spec — drill the flat panels *before*
glue-up, build the carcass bottom-to-sides, fit the back, hang the fronts last —
each step naming the part IDs, hardware, and joinery it touches, so a shop can
work down a checklist that cross-references every other output.

Pure logic — no CAD dependency. The ordering encodes good shop practice; the
content is derived from the same cut list, drilling, and joinery the rest of the
pipeline produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsl import CabinetSpec, TableSpec, ComponentGroup, Construction
from .cutlist import generate_cutlist
from .geometry import component_tag


@dataclass
class AssemblyStep:
    number: int
    title: str
    detail: str
    part_ids: list[str] = field(default_factory=list)
    hardware: list[str] = field(default_factory=list)
    category: str = "assembly"   # prep | joinery | carcass | fronts | hardware | finish


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


def _cabinet_sequence(spec: CabinetSpec, cl) -> list[AssemblySequence]:
    parts = cl.parts
    all_ids = [p.id for p in parts if p.id]
    sides = _ids(parts, "side")
    carcass = _ids(parts, "side", "bottom", "top", "stretcher")
    back = _ids(parts, "back panel", "back")
    shelves = _ids(parts, "shelf")
    fronts = _ids(parts, "door", "drawer front", "mullion", "filler")
    boxes = _ids(parts, "box")
    frame = _ids(parts, "frame", "stile", "rail")
    toe = _ids(parts, "toe")
    hw = {h.name for h in cl.hardware}
    is_ff = spec.construction == Construction.FACE_FRAME

    steps: list[AssemblyStep] = []
    n = 0

    def step(title, detail, part_ids=None, hardware=None, category="assembly"):
        nonlocal n
        n += 1
        steps.append(AssemblyStep(n, title, detail, part_ids or [],
                                  hardware or [], category))

    step("Mill & label all parts",
         "Cut every panel to the sizes on the cut list and label each with its "
         "ID; check material grain runs as marked.", all_ids, category="prep")
    drill_ids = sorted(set(sides + fronts))
    step("Drill the flat panels first",
         "Bore the 32mm shelf-pin lines, hinge cups and slide/plate holes while "
         "the panels are flat and easy to register — before any glue-up.",
         drill_ids,
         [h for h in ("Shelf pin", "Concealed hinge") if h in hw], "prep")
    step("Cut the joinery",
         "Run the carcass dados/rabbets and the back housing per the joinery "
         "setup sheet; dry-fit and check for square.", sides, category="joinery")
    step("Glue & clamp the carcass",
         "Assemble bottom and top/stretchers between the sides, glue and clamp, "
         "and check diagonals equal before the glue sets.", carcass,
         category="carcass")
    if back:
        step("Fit the back",
             "Seat the back in its rabbet/groove (or apply it) to square and "
             "stiffen the box.", back, ["Back panel screw 4×16"], "carcass")
    if toe:
        step("Attach the toe kick", "Fix the toe kick to the cabinet base.",
             toe, category="carcass")
    if is_ff and frame:
        step("Attach the face frame",
             "Glue/pocket-screw the stiles and rails to the carcass front and "
             "flush-trim.", frame, category="carcass")
    if boxes:
        step("Build drawer boxes & mount slides",
             "Assemble the drawer boxes, install the slides in the cabinet, and "
             "fit each box; adjust for even reveals.", boxes,
             [h for h in hw if "slide" in h.lower()], "fronts")
    if any(p.id for p in parts if "drawer front" in p.name.lower()):
        step("Fit the drawer fronts",
             "Attach the drawer fronts to the boxes and set consistent gaps.",
             _ids(parts, "drawer front"), [h for h in hw if "pull" in h.lower()],
             "fronts")
    if any("door" in p.name.lower() for p in parts):
        step("Hang the doors",
             "Bore/mount the hinges and plates, hang the doors, and adjust the "
             "three-way for even reveals.", _ids(parts, "door"),
             [h for h in hw if "hinge" in h.lower() or "plate" in h.lower()],
             "fronts")
    final_ids = shelves
    step("Install hardware & shelves",
         "Fit pulls, shelf pins and adjustable shelves, and any remaining "
         "hardware.", final_ids,
         [h for h in hw if "pull" in h.lower() or "pin" in h.lower()], "hardware")
    step("Sand & finish",
         "Final-sand, ease the edges, and apply the finish schedule.",
         category="finish")
    return [AssemblySequence(spec.name, steps)]


def _table_sequence(spec: TableSpec, cl) -> AssemblySequence:
    parts = cl.parts
    legs = _ids(parts, "leg")
    aprons = _ids(parts, "apron")
    top = _ids(parts, "top")
    steps = [
        AssemblyStep(1, "Mill all parts", "Dress the top, legs and aprons to "
                     "size.", [p.id for p in parts if p.id], category="prep"),
        AssemblyStep(2, "Cut leg-to-apron joints", "Mortise the legs and tenon "
                     "the aprons (or Domino/dowel) per the joinery sheet.",
                     legs + aprons, category="joinery"),
        AssemblyStep(3, "Glue up the base", "Glue the end assemblies, then join "
                     "with the long aprons; check for square and wind.",
                     legs + aprons, category="carcass"),
        AssemblyStep(4, "Attach the top", "Fasten the top with a method that "
                     "allows seasonal movement (figure-8s / Z-clips).", top,
                     ["Tabletop fastener"], "hardware"),
        AssemblyStep(5, "Sand & finish", "Final-sand and apply the finish.",
                     category="finish"),
    ]
    return AssemblySequence(spec.name, steps)


def assembly_sequence(spec) -> AssemblySequence:
    """Ordered build sequence for a cabinet, table, or group."""
    if isinstance(spec, ComponentGroup):
        seq = AssemblySequence(spec.name)
        n = 0
        for i, comp in enumerate(spec.components, start=1):
            tag = component_tag(comp, i)
            for s in assembly_sequence(comp.spec).steps:
                n += 1
                seq.steps.append(AssemblyStep(
                    n, f"[{tag}] {s.title}", s.detail,
                    [f"{tag}-{pid}" for pid in s.part_ids], s.hardware, s.category))
        n += 1
        seq.steps.append(AssemblyStep(
            n, "Set & join the run",
            "Level each cabinet, shim to the floor, clamp faces flush and screw "
            "the cabinets together; scribe end panels/fillers to the walls.",
            category="install"))
        return seq
    cl = generate_cutlist(spec)
    if isinstance(spec, TableSpec):
        return _table_sequence(spec, cl)
    return _cabinet_sequence(spec, cl)[0]
