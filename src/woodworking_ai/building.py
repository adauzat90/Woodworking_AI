"""Building / barndominium structural frame — auto-placed beams + posts.

A :class:`~dsl.BuildingFrameSpec` is a *leaf* like any furniture type, but at
building scale: instead of the designer listing every beam, this module **places
them automatically**. Given the building envelope and a beam/post make-up it:

1. lays a set of parallel **carrying-beam lines** across the building, and
2. drops **support posts** along each beam, choosing the bay spacing so no beam
   clear-spans further than it can safely carry the declared area load
   (:func:`engineering.max_beam_span`).

The result is the primary skeleton only — beams and the posts under them. Roof
trusses, rafters, purlins, wall girts, sheathing and foundations are out of
scope for this type.

:func:`frame_plan` is the **single source of placement truth**: the geometry
(``panels``), the cut list, the validator, the joinery and the assembly plan all
read it, so the 3D model, the parts a shop buys and the checks can never drift.
Pure math — no CAD dependency.

Coordinates use the shared frame with the footprint centred on the origin:
X = length (centred), Y = width (centred), Z = height (floor at 0). Posts run
from the floor to the underside of the beams; the beams sit on top so a beam's
top face is at ``wall_height``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import furniture
from . import engineering
from .dispatch import BUILDING
from .dsl import BuildingFrameSpec, BeamMaterial, SpanDirection
from .geometry import PanelBox
from .cutlist import CutList, Part, Hardware, assign_ids, resolve_part_stock
from .materials import MAT_SOLID
from .validator import Issue
from .joinery import JoineryOp
from .assembly_steps import SubAssembly, step


GRAVITY = 9.80665  # m/s²

# Default beam-line spacing when the spec leaves ``beam_spacing`` at 0. ~16 ft is
# a common girder-line tributary for a wood-framed building.
DEFAULT_BEAM_LINE_SPACING = 4877.0

# Posts no slimmer than this slenderness (height / least side) get a warning — a
# tall, thin timber column is prone to buckling.
MAX_POST_SLENDERNESS = 50.0


# ---------------------------------------------------------------------------
# Placement plan — the single source of truth
# ---------------------------------------------------------------------------

@dataclass
class PlacedMember:
    """One placed structural member in the shared (X, Y, Z) frame.

    ``size`` and ``center`` are (x, y, z) triples in mm. ``kind`` is ``"beam"`` or
    ``"post"``; ``label`` is a stable, human name used across every output.
    """
    kind: str
    label: str
    size: tuple[float, float, float]
    center: tuple[float, float, float]


@dataclass
class FramePlan:
    """The computed auto-placement for a building frame.

    Everything downstream (geometry, cut list, validator, joinery, assembly)
    derives from this one object, so the model and the parts list cannot diverge.
    """
    beams: list[PlacedMember] = field(default_factory=list)
    posts: list[PlacedMember] = field(default_factory=list)

    n_lines: int = 0          # parallel beam lines across the building
    posts_per_beam: int = 0   # support posts along each beam (incl. both ends)
    n_bays: int = 0           # clear spans between posts along a beam
    beam_run: float = 0.0     # length of one beam (mm)
    line_spacing: float = 0.0  # c/c of the beam lines (tributary width, mm)
    clear_span: float = 0.0   # actual clear span between posts (mm)
    max_span: float = 0.0     # allowable clear span used for the layout (mm)
    post_height: float = 0.0  # floor to underside of beam (mm)
    line_load: float = 0.0    # design line load on a beam (N/mm)

    @property
    def n_posts(self) -> int:
        return len(self.posts)

    @property
    def n_beams(self) -> int:
        return len(self.beams)


def _line_load_per_mm(spec: BuildingFrameSpec, tributary: float) -> float:
    """Design line load on one beam (N/mm) for a *tributary* width (mm).

    ``design_load`` is a supported area load in kg/m²; a beam carries a strip the
    width of its line spacing. kg/m² · g → N/m²; × tributary(m) → N/m; ÷1000 → N/mm.
    """
    area_load = max(float(spec.design_load), 0.0)            # kg/m²
    trib_m = max(tributary, 0.0) / 1000.0                    # m
    return area_load * GRAVITY * trib_m / 1000.0            # N/mm


def _axes(spec: BuildingFrameSpec) -> tuple[float, float]:
    """``(run, repeat)`` lengths — the axis beams run along, and the one lines
    repeat across.

    Beams run along ``span_direction``; parallel lines repeat across the other
    axis. ``width`` runs beams across the building (the short way); the default
    ``length`` runs them the long way.
    """
    if spec.span_direction == SpanDirection.WIDTH:
        return float(spec.width), float(spec.length)
    return float(spec.length), float(spec.width)


def _centred(total: float, n: int, inset: float) -> list[float]:
    """``n`` positions centred on 0, evenly spaced across *total* with the two
    outer positions set in by *inset* from each edge (so a member of width
    ``2·inset`` sits flush with the footprint line)."""
    usable = max(total - 2.0 * inset, 0.0)
    if n <= 1:
        return [0.0]
    return [-usable / 2.0 + usable * i / (n - 1) for i in range(n)]


def frame_plan(spec: BuildingFrameSpec) -> FramePlan:
    """Auto-place the carrying beams and support posts for *spec*.

    The single source of placement truth (see the module docstring). Beam lines
    are spaced across the building; along each beam the posts are spaced so the
    clear span stays within the safe span for the section + load (or an explicit
    ``post_spacing`` / ``max_span`` when given).

    World axes: ``width`` runs along X, ``length`` along Y, height along Z, with
    the footprint centred on the origin. The outer posts are inset by half a post
    so their outer faces land on the footprint lines, and each beam runs flush to
    the footprint along its run axis — so the bounding box is exactly
    ``width × length × wall_height``.
    """
    run_dim, rep_dim = _axes(spec)
    beam_depth = float(spec.beam_depth)
    beam_width = float(spec.beam_width)
    post_size = float(spec.post_size)
    wall_height = float(spec.wall_height)

    # Beam lines across the repeat axis (always including the two outer walls).
    line_spacing_in = spec.beam_spacing if spec.beam_spacing > 0 \
        else DEFAULT_BEAM_LINE_SPACING
    if rep_dim > 0 and line_spacing_in > 0:
        n_lines = max(2, round(rep_dim / line_spacing_in) + 1)
    else:
        n_lines = 2
    line_spacing = rep_dim / (n_lines - 1) if n_lines > 1 else rep_dim

    # Safe clear span for this beam under its tributary load, then bay layout.
    line_load = _line_load_per_mm(spec, line_spacing)
    modulus = engineering.beam_modulus(spec.beam_material, spec.species)
    safe_span = engineering.max_beam_span(
        beam_width, beam_depth, modulus, line_load,
        deflection_ratio=max(float(spec.deflection_ratio), 1.0))
    max_span = float(spec.max_span) if spec.max_span > 0 else safe_span

    if spec.post_spacing > 0:
        n_bays = max(1, round(run_dim / spec.post_spacing))
    elif max_span > 0:
        n_bays = max(1, math.ceil(run_dim / max_span))
    else:
        n_bays = 1
    posts_per_beam = n_bays + 1
    clear_span = run_dim / n_bays if n_bays else run_dim

    post_height = max(wall_height - beam_depth, 0.0)
    beam_cz = post_height + beam_depth / 2.0   # beam sits on top of the posts

    half = post_size / 2.0
    run_positions = _centred(run_dim, posts_per_beam, half)   # post centres, run
    line_positions = _centred(rep_dim, n_lines, half)         # beam/post lines

    along_y = spec.span_direction != SpanDirection.WIDTH

    def to_xy(run_c: float, rep_c: float) -> tuple[float, float]:
        """Map a centred (run, repeat) coordinate to world (x, y).

        Default (beams run the length): run axis = Y, repeat axis = X. Beams
        across the width instead put the run axis on X.
        """
        return (rep_c, run_c) if along_y else (run_c, rep_c)

    plan = FramePlan(
        n_lines=n_lines, posts_per_beam=posts_per_beam, n_bays=n_bays,
        beam_run=run_dim, line_spacing=line_spacing, clear_span=clear_span,
        max_span=max_span, post_height=post_height, line_load=line_load)

    # A beam runs the full footprint along its run axis (flush, bearing on the
    # inset end posts); it is ``beam_width`` thick across the repeat axis.
    beam_size = (beam_width, run_dim, beam_depth) if along_y \
        else (run_dim, beam_width, beam_depth)
    for j, rep_c in enumerate(line_positions, start=1):
        bx, by = to_xy(0.0, rep_c)   # beam centred on its run axis
        plan.beams.append(PlacedMember(
            "beam", f"Beam line {j}", beam_size, (bx, by, beam_cz)))
        for i, run_c in enumerate(run_positions, start=1):
            px, py = to_xy(run_c, rep_c)
            plan.posts.append(PlacedMember(
                "post", f"Post L{j}.{i}", (post_size, post_size, post_height),
                (px, py, post_height / 2.0)))
    return plan


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def _panels(spec: BuildingFrameSpec) -> list[PanelBox]:
    """Place every beam and post as a :class:`PanelBox` for the 3D model."""
    plan = frame_plan(spec)
    panels: list[PanelBox] = []
    for b in plan.beams:
        panels.append(PanelBox(b.label, b.size, b.center,
                               category="beam", subassembly="Beams"))
    for p in plan.posts:
        panels.append(PanelBox(p.label, p.size, p.center,
                               category="post", subassembly="Posts"))
    return panels


def _beam_make_up(spec: BuildingFrameSpec, plan: FramePlan) -> list[Part]:
    """The carrying-beam parts: laminated plies for built-up, else solid members."""
    cs = f"{plan.clear_span / 1000.0:.1f}m clear spans"
    if spec.beam_material == BeamMaterial.BUILT_UP and spec.beam_plies > 1:
        ply_t = spec.beam_width / spec.beam_plies
        return [Part(
            "Carrying beam ply", plan.n_lines * spec.beam_plies,
            length=plan.beam_run, width=spec.beam_depth, thickness=ply_t,
            material=MAT_SOLID, grain="length",
            notes=(f"laminate {spec.beam_plies} plies into each of "
                   f"{plan.n_lines} built-up girders; {cs}"))]
    return [Part(
        "Carrying beam", plan.n_lines,
        length=plan.beam_run, width=spec.beam_depth, thickness=spec.beam_width,
        material=MAT_SOLID, grain="length",
        notes=f"{str(spec.beam_material).replace('_', ' ')} girder; {cs}")]


def _cutlist(spec: BuildingFrameSpec) -> CutList:
    cl = CutList(spec_name=spec.name)
    plan = frame_plan(spec)

    cl.parts.extend(_beam_make_up(spec, plan))
    cl.parts.append(Part(
        "Support post", plan.n_posts,
        length=plan.post_height, width=spec.post_size, thickness=spec.post_size,
        material=MAT_SOLID, grain="length",
        notes=(f"{str(spec.post_material).replace('_', ' ')} column; "
               f"{plan.posts_per_beam} per beam line")))

    # Structural connectors (one per post: a base anchor and a beam cap).
    cl.hardware.append(Hardware(
        "Post base anchor", plan.n_posts,
        "anchor each column base to the slab/pier", category="connector"))
    cl.hardware.append(Hardware(
        "Post-to-beam cap", plan.n_posts,
        "tie each beam down to the post below it", category="connector"))
    if spec.beam_material == BeamMaterial.BUILT_UP and spec.beam_plies > 1:
        # ~1 row of through-bolts every 600mm along each built-up girder.
        bolts = plan.n_lines * max(2, math.ceil(plan.beam_run / 600.0)) * 2
        cl.hardware.append(Hardware(
            "Beam lamination bolts", bolts,
            "bolt/nail the girder plies together per the lamination schedule",
            category="fastener"))

    resolve_part_stock(cl.parts, spec)
    assign_ids(cl.parts)
    return cl


def _validate(spec: BuildingFrameSpec) -> list[Issue]:
    issues: list[Issue] = []

    def err(f, m, **kw):
        issues.append(Issue("error", f, m, **kw))

    def warn(f, m, **kw):
        issues.append(Issue("warning", f, m, **kw))

    def info(f, m):
        issues.append(Issue("info", f, m))

    dims = {
        "length": spec.length, "width": spec.width, "wall_height": spec.wall_height,
        "beam_width": spec.beam_width, "beam_depth": spec.beam_depth,
        "post_size": spec.post_size,
    }
    for name, v in dims.items():
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            err(name, f"must be a positive, finite number, got {v!r}")
    if any(i.severity == "error" for i in issues):
        return issues

    if spec.beam_depth >= spec.wall_height:
        err("beam_depth",
            "beam is as tall as the wall — no room for posts beneath it; "
            "lower the beam or raise the wall height", rule_id="BLD-001")
        return issues

    plan = frame_plan(spec)

    # The placed clear span must stay within the safe span for the section/load.
    if plan.max_span > 0 and plan.clear_span > plan.max_span + 1.0:
        ratio = engineering.beam_deflection_ratio(
            plan.clear_span, spec.beam_width, spec.beam_depth,
            engineering.beam_modulus(spec.beam_material, spec.species),
            plan.line_load)
        err("post_spacing",
            f"beams clear-span {plan.clear_span / 1000.0:.1f}m but can safely "
            f"span only ~{plan.max_span / 1000.0:.1f}m at this section and load "
            f"(L/{ratio:.0f} < L/{spec.deflection_ratio:.0f}) — add posts "
            "(closer post_spacing), deepen the beam, or add plies",
            rule_id="BLD-002", observed=round(plan.clear_span, 1),
            limit=round(plan.max_span, 1), units="mm", direction="max")

    # Slender timber columns buckle; flag a tall, thin post.
    least_side = min(spec.post_size, spec.post_size)
    if least_side > 0:
        slenderness = plan.post_height / least_side
        if slenderness > MAX_POST_SLENDERNESS:
            warn("post_size",
                 f"posts are slender (height/side ≈ {slenderness:.0f} > "
                 f"{MAX_POST_SLENDERNESS:.0f}) and may buckle — use a larger "
                 "section or brace them",
                 rule_id="BLD-003", observed=round(slenderness, 1),
                 limit=MAX_POST_SLENDERNESS, units="", direction="max")

    # A beam laid flatter than it is wide wastes its depth (stiffness ∝ depth³).
    if spec.beam_width > spec.beam_depth:
        warn("beam_depth",
             "the beam is wider than it is deep — turn it on edge (depth > "
             "width) so its full stiffness carries the span", rule_id="BLD-004")

    if spec.design_load <= 0:
        warn("design_load",
             "design_load is zero — the safe-span check can't size the bays; "
             "set the supported area load (≈245 kg/m² ≈ 50 psf for a floor)")

    info("layout",
         f"auto-placed {plan.n_beams} beams on {plan.n_posts} posts: "
         f"{plan.n_lines} beam lines @ {plan.line_spacing / 1000.0:.1f}m c/c, "
         f"{plan.posts_per_beam} posts per beam ({plan.n_bays} bays of "
         f"{plan.clear_span / 1000.0:.1f}m).")
    return issues


def _joinery(spec: BuildingFrameSpec, cl) -> list[JoineryOp]:
    pid = cl.part_id_for_label
    ops: list[JoineryOp] = []
    post_id = pid("Support post")
    ops.append(JoineryOp(
        part="Post base", operation="anchor column to foundation",
        tool="post base / anchor bolts", width=round(spec.post_size, 1),
        depth=0.0, reference="each post base", part_id=post_id,
        note="set columns plumb on their anchors before any beam goes up"))
    beam_label = "Carrying beam ply" \
        if (spec.beam_material == BeamMaterial.BUILT_UP and spec.beam_plies > 1) \
        else "Carrying beam"
    if spec.beam_material == BeamMaterial.BUILT_UP and spec.beam_plies > 1:
        ops.append(JoineryOp(
            part="Built-up girder", operation="laminate plies",
            tool="structural screws / bolts + glue", width=round(spec.beam_width, 1),
            depth=round(spec.beam_depth, 1), reference="full length of each beam",
            part_id=pid(beam_label),
            note=f"nail/bolt {spec.beam_plies} plies into one girder, staggered"))
    ops.append(JoineryOp(
        part="Post-to-beam", operation="seat & tie beam to post",
        tool="post cap / column bracket", width=round(spec.beam_width, 1),
        depth=round(spec.post_size, 1), reference="every post-beam intersection",
        part_id=pid(beam_label),
        note="bear the beam fully on the post and tie it down with a cap"))
    return ops


def _assembly(spec: BuildingFrameSpec, cl) -> list[SubAssembly]:
    parts = cl.parts
    post_ids = [p.id for p in parts if p.id and p.name == "Support post"]
    beam_ids = [p.id for p in parts if p.id and p.name.startswith("Carrying beam")]
    hw = [h.name for h in cl.hardware]

    posts = SubAssembly("Posts", "Stand and plumb the support columns",
                        part_ids=post_ids, category="carcass")
    posts.steps = [
        step(1, "Set out the post grid",
             "Mark the post centres from the plan and set each base anchor.",
             post_ids, [h for h in hw if "anchor" in h.lower()], "carcass"),
        step(2, "Stand & plumb the posts",
             "Stand each column on its anchor, plumb it both ways and brace it "
             "temporarily until the beams lock the frame.", post_ids,
             category="carcass"),
    ]
    beams = SubAssembly("Beams", "Build and set the carrying beams",
                        part_ids=beam_ids, category="carcass")
    bsteps = []
    n = 1
    if spec.beam_material == BeamMaterial.BUILT_UP and spec.beam_plies > 1:
        bsteps.append(step(
            n, "Laminate the girders",
            f"Glue and bolt {spec.beam_plies} plies into each built-up girder "
            "per the joinery sheet; stagger any end joints over a post.",
            beam_ids, [h for h in hw if "lamination" in h.lower()], "carcass"))
        n += 1
    bsteps.append(step(
        n, "Hoist & set the beams",
        "Lift each beam onto the posts, bearing fully on the caps; check the "
        "tops are level and the bays are square before tying down.",
        beam_ids, [h for h in hw if "cap" in h.lower()], "carcass"))
    beams.steps = bsteps

    final = SubAssembly("Final", "Tie the frame together", category="final")
    final.steps = [
        step(1, "Fasten & remove bracing",
             "Tie every beam to its posts, confirm the frame is square and "
             "plumb, then strike the temporary bracing.", category="final"),
    ]
    return [posts, beams, final]


furniture.register(
    BUILDING,
    panels=_panels,
    cut_parts=_cutlist,
    validate=_validate,
    joinery_ops=_joinery,
    assembly=_assembly,
)
