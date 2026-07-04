"""Leaf implementation for the generic ``piece`` type (the taxonomy escape hatch).

A ``piece`` is an explicit list of rectangular parts plus joints (see
:class:`~dsl.PieceSpec`). It exists so an agent can express furniture the closed
taxonomy doesn't cover — a miter station, a lumber rack, garage shelving — and
still get the full pipeline: validation, the interference critic, a cut list,
cost, and 3D export. Like the other home-shop leaves it is pure math: a spec
dataclass in :mod:`dsl`, a :mod:`dispatch` kind, and the five stage callables
registered into :mod:`furniture`. Importing this module wires those
registrations, so every generic stage dispatches to it with no stage-body edits.

Design notes worth reading before touching this module:

* **Identity compile.** ``panels`` places each expanded part exactly at its
  ``at`` + ``size`` — no derivation, no reinterpretation. The placement is the
  single source of truth the builder and the Critic share.
* **Cut dimensions from the box + grain** (see :func:`_cut_dims`): a part's
  *thickness* is its smallest extent (a board is thinnest through its faces);
  the other two extents are the face. When a grain axis is given, the cut-list
  *length* runs along it (and ``grain="length"``); otherwise length is the
  longer face dimension and width the shorter — the convention a cut list /
  nesting tool expects.
* **Generic physics only.** The validator knows nothing about furniture — it
  checks finiteness, positivity, floor clearance, that joints reference real and
  touching parts, flags volume overlaps and floating parts, and (when a material
  form is declared) that a part maps onto real stock.

No CAD dependency.
"""

from __future__ import annotations

import math
from enum import Enum

from . import furniture
from . import stock
from . import components as _components
from . import hardware as hw
from .dispatch import PIECE
from .dsl import PieceSpec
from .geometry import PanelBox
from .cutlist import CutList, Part, Hardware, assign_ids, resolve_part_stock
from .materials import MAT_SOLID, MAT_SHEET, SHEET_FORMS, is_solid_form
from .validator import Issue
from .joinery import JoineryOp


# A single piece is capped so a runaway spec can't flood the pipeline.
_PIECE_MAX_PARTS = 500
# Faces within this gap (mm) count as touching/abutting — a joint, not a gap.
_TOUCH_TOL = 1.0


def _built_components(spec: PieceSpec):
    """``(inst, component)`` for every placed component that builds.

    Unknown or malformed component entries are skipped here (the validator turns
    them into a repairable error) so the panels / cut-list / joinery stages never
    crash on a typo. A component's expanded parts and panels are namespaced with
    ``"{inst.name} "`` so they read distinctly and their IDs don't collide.
    """
    out = []
    for inst in getattr(spec, "components", None) or []:
        try:
            comp = _components.component_from_dict(inst.as_component_dict())
        except Exception:
            continue
        out.append((inst, comp))
    return out


def _prefix(inst) -> str:
    return f"{inst.name} " if inst.name else ""


# ===========================================================================
# Geometry helpers (min-corner AABBs, adapted from the Critic's overlap test)
# ===========================================================================

def _corners(at, size) -> tuple[tuple, tuple]:
    """A part's ``(min_corner, max_corner)`` from its min corner + extent."""
    return at, (at[0] + size[0], at[1] + size[1], at[2] + size[2])


def _interpenetration(a, b) -> tuple[float, float, float]:
    """Per-axis overlap depth of two ``(min, max)`` boxes (negative => a gap).

    The same measure the Critic's ``_overlap`` uses, on min-corner boxes.
    """
    return tuple(min(a[1][ax], b[1][ax]) - max(a[0][ax], b[0][ax])
                 for ax in range(3))


def _boxes_touch(a, b) -> bool:
    """True when two boxes abut or overlap (every axis within the touch tol)."""
    return all(o >= -_TOUCH_TOL for o in _interpenetration(a, b))


def _boxes_overlap(a, b) -> bool:
    """True when two boxes share positive volume on every axis (a collision)."""
    return all(o > _TOUCH_TOL for o in _interpenetration(a, b))


def _cut_dims(size, grain_axis: str):
    """Cut ``(length, width, thickness, grain)`` for a box of *size*.

    Thickness is the smallest extent; the other two extents form the face. With a
    usable grain axis the length runs along it (grain ``"length"``); otherwise
    length is the longer face dimension (grain ``"none"``).
    """
    dims = (("x", size[0]), ("y", size[1]), ("z", size[2]))
    thick_axis, thickness = min(dims, key=lambda kv: kv[1])
    face = [kv for kv in dims if kv[0] != thick_axis]
    if grain_axis in ("x", "y", "z") and grain_axis != thick_axis:
        face_by = dict(face)
        length = face_by[grain_axis]
        width = next(v for k, v in face if k != grain_axis)
        return length, width, thickness, "length"
    long_face, short_face = sorted((v for _k, v in face), reverse=True)
    return long_face, short_face, thickness, "none"


# ===========================================================================
# Stage: panels (the identity compile)
# ===========================================================================

def _piece_panels(spec: PieceSpec) -> list[PanelBox]:
    """Each expanded part -> one :class:`PanelBox` at its position/size.

    Dead simple by design: a box placed by its centre (``at`` + ``size`` / 2) in
    the shared frame. This placement is the single source of truth shared by the
    builder and the Critic.
    """
    panels: list[PanelBox] = []
    for part in spec.parts:
        for name, at, size in part.placements():
            center = (at[0] + size[0] / 2, at[1] + size[1] / 2, at[2] + size[2] / 2)
            panels.append(PanelBox(
                name, (size[0], size[1], size[2]), center,
                "carcass", subassembly="Parts"))
    # Each placed component expands into its own panels, namespaced by instance.
    for inst, comp in _built_components(spec):
        pfx = _prefix(inst)
        for p in comp.panels():
            p.label = f"{pfx}{p.label}"
            p.subassembly = inst.name or p.subassembly
            panels.append(p)
    return panels


# ===========================================================================
# Stage: cut list
# ===========================================================================

def _piece_cutlist(spec: PieceSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    g_form = spec.material_form
    overrides: list[tuple[Part, str, str]] = []
    for part in spec.parts:
        form = part.material_form or g_form
        material = MAT_SOLID if is_solid_form(form) else MAT_SHEET
        for name, _at, size in part.placements():
            length, width, thickness, pgrain = _cut_dims(size, part.grain)
            note = f"grain along {part.grain.upper()}" if part.grain != "none" \
                else "no grain (sheet/square stock)"
            p = Part(name, 1, length=round(length, 1), width=round(width, 1),
                     thickness=round(thickness, 1), material=material,
                     grain=pgrain, notes=note)
            cl.parts.append(p)
            overrides.append((p, part.material_form, part.species))

    # Each placed component contributes its raw cut parts, namespaced by instance;
    # a component that declares its own material_form/species overrides its parts.
    for inst, comp in _built_components(spec):
        pfx = _prefix(inst)
        c_form = str(getattr(comp, "material_form", "") or "")
        c_species = str(getattr(comp, "species", "") or "")
        for cp in comp.cut_parts():
            cp.name = f"{pfx}{cp.name}"
            cl.parts.append(cp)
            overrides.append((cp, c_form, c_species))

    # Resolve each part's physical stock from the spec globals + any `stock`
    # override (the shared convention), then let a PER-PART form/species win.
    resolve_part_stock(cl.parts, spec)
    for p, ov_form, ov_species in overrides:
        if ov_form:
            p.form = ov_form
            p.material = MAT_SOLID if is_solid_form(p.form) else MAT_SHEET
        if ov_species:
            p.species = ov_species

    _piece_hardware(cl, spec)
    assign_ids(cl.parts)
    return cl


def _piece_hardware(cl: CutList, spec: PieceSpec) -> None:
    """Emit assembly screws for the screwed / pocket-hole joints (modest count).

    Mirrors the other leaves' habit of turning fastener joints into a buyable
    BOM line; captured joints (dado/rabbet/domino/dovetail…) are glued and add
    no fastener.
    """
    screwed = sum(1 for j in spec.joints if _joint_key(j) in ("screw", "pocket"))
    if screwed:
        cl.hardware.append(Hardware(
            hw.ASSEMBLY_SCREW.name, screwed * 4,
            "~4 per screwed / pocket-hole joint", sku=hw.ASSEMBLY_SCREW.sku,
            category="fastener"))


def _joint_key(joint) -> str:
    j = joint.joinery
    return (j.value if isinstance(j, Enum) else str(j)).strip().lower()


# ===========================================================================
# Stage: validate (generic physics — no furniture semantics)
# ===========================================================================

def _piece_validate(spec: PieceSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m, rule=""):
        issues.append(Issue("error", f, m, rule))

    def warn(f, m, rule=""):
        issues.append(Issue("warning", f, m, rule))

    def info(f, m, rule=""):
        issues.append(Issue("info", f, m, rule))

    # --- placed components: unknown names + each block's own compiler rules ---
    # A component instance carries its OWN validate(); its issues are re-labelled
    # with the instance name so the repair loop can target them. An unknown
    # component name is a repairable load error here, not a crash downstream.
    built = []
    for inst in getattr(spec, "components", None) or []:
        label = inst.name or inst.component or "?"
        if not _components.is_component(inst.component):
            err("components",
                f"component {label!r} names unknown building block "
                f"{inst.component!r}; available: "
                f"{', '.join(_components.available_components())}")
            continue
        try:
            comp = _components.component_from_dict(inst.as_component_dict())
        except Exception as exc:                       # pragma: no cover - defensive
            err("components", f"component {label!r} failed to build: {exc}")
            continue
        built.append((inst, comp))
        for iss in comp.validate():
            issues.append(Issue(iss.severity, f"{label}.{iss.field}",
                                f"{label}: {iss.message}", iss.rule_id))

    declared = spec.parts
    if not declared and not built:
        err("parts", "a piece needs at least one part or component")
        return issues

    # --- unique, non-empty declared names --------------------------------
    names = [p.name for p in declared]
    seen: set[str] = set()
    dups: set[str] = set()
    for n in names:
        if not n:
            err("parts", "every part needs a non-empty name")
        elif n in seen:
            dups.add(n)
        else:
            seen.add(n)
    for n in sorted(dups):
        err("parts", f"duplicate part name {n!r}; part names must be unique")

    # --- expand the array sugar and cap the count ------------------------
    placed: list[tuple[str, str, tuple, tuple]] = []   # (name, base, at, size)
    for p in declared:
        for name, at, size in p.placements():
            placed.append((name, p.name, at, size))
    if len(placed) > _PIECE_MAX_PARTS:
        err("parts",
            f"{len(placed)} parts exceeds the {_PIECE_MAX_PARTS}-part cap for a "
            "single piece; split it into sub-assemblies")
        return issues

    # Component-expanded parts join the free-form parts in the shared physics:
    # they must not overlap or float relative to each other or the free parts.
    for inst, comp in built:
        pfx = _prefix(inst)
        for p in comp.panels():
            sx, sy, sz = p.size
            cx, cy, cz = p.center
            at = (cx - sx / 2, cy - sy / 2, cz - sz / 2)
            placed.append((f"{pfx}{p.label}", inst.name, at, (sx, sy, sz)))

    # --- per-part geometry: finite, positive, on or above the floor ------
    for name, _base, at, size in placed:
        if not all(math.isfinite(v) for v in at):
            err("parts", f"part {name!r} has a non-finite position {list(at)}")
        elif math.isfinite(at[2]) and at[2] < -_TOUCH_TOL:
            err("parts", f"part {name!r} sits below the floor "
                f"(z={at[2]:.0f} < 0)")
        if any((not math.isfinite(v)) or v <= 0 for v in size):
            err("parts", f"part {name!r} has a non-positive or non-finite "
                f"size {list(size)}")
    if any(i.severity == "error" for i in issues):
        # Geometry is unusable for the relational checks below; stop here so the
        # designer fixes the basics first.
        return issues

    boxes = [(name, base, *_corners(at, size)) for name, base, at, size in placed]

    # --- volume overlaps (warning; the critic also flags these) ----------
    # A faster repair signal than waiting for the geometry critic.
    touches = [False] * len(boxes)
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            bi = (boxes[i][2], boxes[i][3])
            bj = (boxes[j][2], boxes[j][3])
            if _boxes_touch(bi, bj):
                touches[i] = touches[j] = True
            if _boxes_overlap(bi, bj):
                warn("parts",
                     f"parts {boxes[i][0]!r} and {boxes[j][0]!r} overlap in "
                     "volume; the geometry critic will flag this interference too")

    # --- floating parts (warning) ----------------------------------------
    for idx, (name, _base, mn, _mx) in enumerate(boxes):
        on_floor = mn[2] <= _TOUCH_TOL
        if not on_floor and not touches[idx]:
            warn("parts",
                 f"part {name!r} floats free — it touches neither the floor nor "
                 "another part; reposition it or add a supporting part")

    # --- joints reference real, touching parts ---------------------------
    by_base: dict[str, list[tuple]] = {}
    for _name, base, mn, mx in boxes:
        by_base.setdefault(base, []).append((mn, mx))
    declared_names = set(names)
    for joint in spec.joints:
        a, b = joint.parts
        unknown = [pn for pn in (a, b) if pn not in declared_names]
        for pn in unknown:
            err("joints", f"joint references unknown part {pn!r}")
        if unknown:
            continue
        if a == b:
            err("joints", f"joint joins part {a!r} to itself")
            continue
        if not any(_boxes_touch(ba, bb)
                   for ba in by_base.get(a, []) for bb in by_base.get(b, [])):
            err("joints",
                f"joint between {a!r} and {b!r} joins parts that don't touch "
                "(their faces neither abut nor overlap); move them together or "
                "remove the joint")

    # --- buildable from real stock, when a material form is declared -----
    for p in declared:
        form = p.material_form or spec.material_form
        if not form:
            continue
        _name, _at, size = p.placements()[0]
        if any(not math.isfinite(v) for v in size):
            continue
        _l, _w, thickness, _g = _cut_dims(size, p.grain)
        if is_solid_form(form):
            if stock.required_quarter(thickness) is None:
                info("parts",
                     f"part {p.name!r}: a {thickness:.0f}mm solid part is thicker "
                     "than 12/4 stock surfaces to; laminate two boards or thin it",
                     "MAT-003")
        elif form in SHEET_FORMS and not stock.is_standard_sheet_thickness(thickness):
            info("parts",
                 f"part {p.name!r}: {thickness:.1f}mm is not a stocked sheet "
                 f"thickness; nearest is "
                 f"{stock.nearest_sheet_thickness(thickness):.0f}mm", "MAT-001")

    return issues


# ===========================================================================
# Stage: joinery ops
# ===========================================================================

# Cut params per joint, keyed by the Joinery vocabulary: (tool, width, depth, note).
_JOINT_OPS = {
    "screw": ("drill / driver", 0.0, 0.0, "pilot + countersink; glue optional"),
    "pocket": ("pocket-hole jig", 0.0, 0.0, "pocket screws + glue"),
    "dowel": ("doweling jig (8mm)", 8.0, 30.0, "two dowels per joint"),
    "domino": ("Festool Domino (8mm)", 8.0, 25.0, "loose-tenon joint"),
    "dado": ("dado stack / router", 0.0, 0.0, "housed dado, cut to the mating thickness"),
    "rabbet": ("dado / router", 0.0, 0.0, "rabbet, glue + brad"),
    "mortise_tenon": ("mortiser / saw", 0.0, 0.0, "mortise & tenon"),
    "dovetail": ("dovetail jig / saw", 0.0, 0.0, "dovetail corner; tails resist pull-apart"),
    "box": ("box-joint jig", 0.0, 0.0, "finger joint"),
    "butt": ("glue-up", 0.0, 0.0, "glued butt joint (weak; consider a mechanical joint)"),
}


def _piece_joinery(spec: PieceSpec, cl: CutList) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops: list[JoineryOp] = []
    for joint in spec.joints:
        a, b = joint.parts
        if not a or not b:
            continue
        jk = _joint_key(joint)
        tool, width, depth, note = _JOINT_OPS.get(
            jk, ("shop method", 0.0, 0.0, f"{jk} joint"))
        ops.append(JoineryOp(
            part=f"{a} / {b}", operation=f"{jk.replace('_', ' ')} joint",
            tool=tool, width=width, depth=depth, reference=f"{a} to {b}",
            part_id=pid(a), note=note))
    # Each component contributes its own internal joinery, resolved against its
    # namespaced part names in the merged cut list.
    for inst, comp in _built_components(spec):
        ops.extend(comp.joinery_ops(cl, prefix=_prefix(inst)))
    return ops


# The assembly stage is intentionally not registered: a generic ``piece`` uses
# the registry's default one-unit "Build" plan (furniture._default_assembly),
# which is the honest plan for an arbitrary parts-and-joints object.
furniture.register(
    PIECE,
    panels=_piece_panels,
    cut_parts=_piece_cutlist,
    validate=_piece_validate,
    joinery_ops=_piece_joinery,
)
