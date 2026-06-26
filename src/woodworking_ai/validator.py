"""Deterministic validation of a cabinet spec.

This is *not* an LLM. It applies type/range checks plus woodworking sanity
rules, catching the great majority of design errors before we ever attempt
geometry. It returns structured issues so the designer agent can self-repair.

No CAD dependency — runs anywhere, instantly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .dsl import (
    TableSpec, ComponentGroup, CabinetType, Joinery, ApplianceVoid,
    CornerJoint, DovetailTails, SlideType, APPLIANCE_VOID_TOLERANCE,
    joinery_key,
)
from .dispatch import spec_kind, VOID, GROUP, TABLE, CABINET
from . import engineering, stock, proportion, furniture
from .hardware import longest_slide_for
from .geometry import front_plan, footprints_overlap, component_tag
from .constants import (
    SLIDE_SIDE_CLEARANCE, SYSTEM_PITCH, HINGE_CUP_DIA, HINGE_CUP_DEPTH,
    HINGE_CUP_INSET, DRAWER_BOX_DEPTH_GAP,
)

# ASTM F2057 scope: clothing storage units >= 27in (686mm) tall fall under the
# CPSC tip-over standard. Toe-kick minimums per ANSI/KCMA A161.1 (2in x 3in).
F2057_HEIGHT_MM = 686.0
KCMA_TOE_MIN_HEIGHT = 75.0   # ~3 in
KCMA_TOE_MIN_SETBACK = 50.0  # ~2 in deep

SIDE_MOUNT_CLEARANCE = SLIDE_SIDE_CLEARANCE  # per-side gap for side-mount slides
MIN_DRAWER_BOX_WIDTH = 150.0 # below this a box is barely usable
# Depth left unused beyond the largest fitting standard slide before it's worth
# flagging: a deeper cabinet could take the next 50mm slide size.
SLIDE_DEPTH_WASTE_MM = 60.0

# Cup outer edge reaches INSET + DIA/2 from the hinge edge; the door must be at
# least this wide to host the bore, plus a little material for strength.
HINGE_MIN_DOOR_WIDTH = HINGE_CUP_INSET + HINGE_CUP_DIA / 2  # 40mm hard minimum
HINGE_MIN_DOOR_BACKING = 3.0  # material left behind the cup

# Drawer-corner joints that properly resist the pull-apart load of opening.
STRONG_DRAWER_JOINTS = {"dovetail", "box", "rabbet", "locking_rabbet"}

# 32mm System constants for the grid feasibility check (SYSTEM_PITCH shared).
PIN_END_MARGIN = 64.0        # first/last system hole in from the panel ends
ROW_SETBACK = 37.0           # each pin row in from the front / back edge
MIN_PIN_POSITIONS = 3        # fewer than this is not meaningfully adjustable

# --- A3 joinery / machining feasibility (analytic, no CAD) ---------------
# A housed joint (dado/groove/rabbet) cut too close to a panel's end leaves a
# short-grain "tongue" that splits out; keep it at least ~1x stock thickness in.
END_DISTANCE_FACTOR = 1.0    # min joint-to-end distance, x stock thickness
# A drawer-slide screw line and a shelf-pin hole share a side panel; if their
# heights land within this band the pilots/bores foul each other.
SLIDE_PIN_CLEARANCE = 6.0    # mm vertical clearance wanted between the two
# A grooved back's housing is captured this far in from the rear edge
# (matches joinery.GROOVE_BACK_INSET); a back rabbet that reaches deeper than
# the groove start eats into the same material and the two interfere.
GROOVE_BACK_INSET = 12.0

# Practical bounds that also guard against pathological inputs (huge loops, NaN).
MAX_DIMENSION = 6000.0   # mm — larger than any real cabinet/pantry
MAX_SHELVES = 50
MAX_DRAWERS = 20


@dataclass
class Issue:
    severity: str   # "error" | "warning" | "info"
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue]

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> list[Issue]:
        """Advisory notes (proportion, comfort) — never block a build."""
        return [i for i in self.issues if i.severity == "info"]

    def as_feedback(self) -> str:
        """Human/agent-readable summary used to prompt a repair."""
        if not self.issues:
            return "OK"
        return "\n".join(str(i) for i in self.issues)


def _finite_positive(val: object) -> bool:
    return isinstance(val, (int, float)) and math.isfinite(val) and val > 0


def _validate_table(spec: TableSpec) -> ValidationResult:
    issues: list[Issue] = []

    def err(f, m):
        issues.append(Issue("error", f, m))

    def warn(f, m):
        issues.append(Issue("warning", f, m))

    def info(f, m):
        issues.append(Issue("info", f, m))

    for name in ("width", "depth", "height", "top_thickness", "leg",
                 "apron_height", "apron_thickness", "leg_inset"):
        val = getattr(spec, name)
        if not _finite_positive(val):
            err(name, f"must be a positive, finite number, got {val!r}")
        elif name in ("width", "depth", "height") and val > MAX_DIMENSION:
            err(name, f"exceeds the practical maximum of {MAX_DIMENSION:.0f}mm")
    if any(i.severity == "error" for i in issues):
        return ValidationResult(issues)

    if spec.height <= spec.top_thickness + spec.apron_height:
        err("height", "too short for the top plus an apron")
    if 2 * spec.leg_inset + spec.leg >= min(spec.width, spec.depth):
        err("leg_inset", "legs do not fit within the top with this inset")
    if spec.apron_thickness >= spec.leg:
        warn("apron_thickness", "apron is as thick as the leg; unusual")
    if spec.height < 350 or spec.height > 1200:
        warn("height", "unusual table height (typical 700–760mm)")

    # --- wood movement on a solid top (MOVE-001/002) ---------------------
    # The top's width (depth, Y) runs across the grain and moves seasonally.
    if getattr(spec, "solid_top", True):
        move = engineering.seasonal_movement(
            spec.depth, getattr(spec, "grain", "flatsawn"),
            species=getattr(spec, "species", None))
        if str(getattr(spec, "top_fixing", "floating")).lower() == "fixed":
            err("top_fixing",
                f"a solid top {spec.depth:.0f}mm across the grain moves about "
                f"{move:.1f}mm seasonally; fixing it rigidly will crack it. Use "
                "floating attachment (figure-8 fasteners, Z-clips, or slotted "
                "cleats)")
        elif move >= 6.0:
            warn("top_fixing",
                 f"allow ~{move:.1f}mm of seasonal movement across the "
                 f"{spec.depth:.0f}mm top; ensure the floating attachment has "
                 "room to slide")

    # --- leg-to-apron joinery vs. racking (STRUCT-002) -------------------
    joint = joinery_key(spec, "mortise_tenon")
    if joint in ("pocket", "butt", "screw"):
        warn("joinery",
             f"a {joint.replace('_', ' ')} leg-to-apron joint resists racking "
             "poorly; prefer mortise & tenon, domino, or dowels (with corner "
             "blocks)")

    # --- solid top buildable from real stock (MAT-003) -------------------
    if getattr(spec, "solid_top", True):
        q = stock.required_quarter(spec.top_thickness)
        if q is None:
            warn("top_thickness",
                 f"a {spec.top_thickness:.0f}mm solid top is thicker than 12/4 "
                 "stock surfaces to; laminate two boards or thin the top")

    # --- proportion advisories (PROP-001/002, INFO) ----------------------
    top = proportion.ratio_of(spec.width, spec.depth)
    if proportion.is_awkward(top):
        longer, shorter = max(spec.width, spec.depth), min(spec.width, spec.depth)
        _, short_target = proportion.golden_targets(longer, shorter)
        info("proportion",
             f"top {spec.width:.0f}×{spec.depth:.0f}mm reads as {top:.2f}:1; "
             f"a golden-ratio top (≈{longer:.0f}×{short_target:.0f}mm) is more "
             "pleasing")
    slim = proportion.slenderness(spec.leg, spec.height)
    if slim < proportion.LEG_MIN_RATIO:
        info("leg", f"a {spec.leg:.0f}mm leg looks spindly under a "
                    f"{spec.height:.0f}mm-tall table; ~{spec.height*0.06:.0f}mm "
                    "reads sturdier")
    elif slim > proportion.LEG_MAX_RATIO:
        info("leg", f"a {spec.leg:.0f}mm leg looks heavy for a "
                    f"{spec.height:.0f}mm table; ~{spec.height*0.08:.0f}mm is "
                    "lighter")
    return ValidationResult(issues)


def _validate_void(void: ApplianceVoid) -> ValidationResult:
    """Sanity-check a reserved appliance gap: positive size, sensible width.

    A void carries no carcass, so the only checks are that it has a positive
    footprint and that its width is close to the standard opening for its
    appliance type (a mis-sized gap means the appliance won't slot in, or leaves
    an ugly margin to fill).
    """
    issues: list[Issue] = []
    if not _finite_positive(void.width):
        issues.append(Issue("error", "width",
                            f"appliance gap width must be positive, got {void.width!r}"))
    if not _finite_positive(void.depth):
        issues.append(Issue("error", "depth",
                            f"appliance gap depth must be positive, got {void.depth!r}"))
    nominal = void.nominal_width
    atype = void.type.value if hasattr(void.type, "value") else str(void.type)
    if nominal is not None and _finite_positive(void.width):
        if abs(void.width - nominal) > APPLIANCE_VOID_TOLERANCE:
            issues.append(Issue(
                "warning", "width",
                f"a {atype} gap is usually ~{nominal:.0f}mm; {void.width:.0f}mm is "
                f"off by {abs(void.width - nominal):.0f}mm — the appliance may not "
                "fit or will leave a margin to fill"))
    return ValidationResult(issues)


def _validate_project(project: ComponentGroup) -> ValidationResult:
    """Validate every component and check the group for placement overlaps."""
    issues: list[Issue] = []
    comps = project.components
    if not comps:
        issues.append(Issue("warning", "components", "project has no components"))
    for i, comp in enumerate(comps, start=1):
        tag = component_tag(comp, i)
        for issue in validate(comp.spec).issues:
            issues.append(Issue(issue.severity, f"{tag}.{issue.field}", issue.message))
    # Oriented 2D footprint overlap — components that share floor space would
    # collide. Works for any rotation, so it catches the inner-corner collision
    # where two perpendicular runs of an L/U layout meet.
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            if footprints_overlap(comps[i], comps[j]):
                issues.append(Issue(
                    "error", "placement",
                    f"'{component_tag(comps[i], i + 1)}' and "
                    f"'{component_tag(comps[j], j + 1)}' overlap in plan; space "
                    "them or fit a corner unit / filler between the runs"))
    return ValidationResult(issues)


def joinery_feasibility(spec) -> list[Issue]:
    """A3 analytic joinery-feasibility checks (no CAD).

    Derived from the same arithmetic schedules the shop uses
    (:func:`joinery.joinery_schedule`, :func:`drilling.drilling_schedule`), so
    the warnings name the exact op that fouls. Covers the machining hazards the
    envelope/sag checks miss:

    * a housed joint cut too near a panel end (short-grain blow-out);
    * a drawer-slide screw line colliding with a shelf-pin row on a side; and
    * a grooved back whose housing clashes with the back rabbet/recess.

    The hinge-cup blow-through (depth axis) is the fourth A3 check; it raises a
    hard error inline in :func:`validate` (see the concealed-hinge block).
    """
    from .joinery import joinery_schedule, HOUSED_DEPTH_FRACTION
    from .drilling import drilling_schedule
    from .dsl import BackStyle

    issues: list[Issue] = []
    m = spec.material

    # --- 2) housed joint too close to a panel end (short-grain blow-out) ---
    # A dado/groove/rabbet leaves a ledge of material between the cut and the
    # panel end; under ~1x stock thickness that short-grain ledge splits out.
    # The numerically-located housed joint here is the grooved back, set in
    # GROOVE_BACK_INSET from the rear edge.
    min_end = round(END_DISTANCE_FACTOR * m.carcass, 1)
    try:
        sched = joinery_schedule(spec)
    except Exception as exc:
        # Never silently drop the check: a failed schedule must surface as
        # "could not verify", not as an implicit all-clear (this is a safety
        # check — short-grain blow-out — so a quiet skip reads as "safe").
        sched = None
        issues.append(Issue(
            "warning", "joinery",
            "could not verify the housed-joint short-grain clearance — the "
            f"joinery schedule failed to build ({type(exc).__name__}); review "
            "the joinery manually"))
    if sched is not None:
        for op in sched.ops:
            if "groove for back" not in op.operation or op.depth <= 0:
                continue
            # Distance from the groove to the rear panel end it's cut near.
            if GROOVE_BACK_INSET < min_end:
                issues.append(Issue(
                    "warning", "joinery",
                    f"the {op.operation} on '{op.part}' sits {GROOVE_BACK_INSET:.0f}mm "
                    f"from the rear edge — under ~1x the {m.carcass:.0f}mm stock, so "
                    "the short-grain ledge can blow out; rabbet the back instead or "
                    "increase the inset"))

    # --- 4) grooved back vs. back rabbet/recess interference ---------------
    # A captured (grooved) back is housed GROOVE_BACK_INSET in from the rear and
    # cut HOUSED_DEPTH_FRACTION of the side's thickness deep. The groove plus the
    # rear recess (the back's own seat) must not consume the whole rear corner:
    # if the groove housing reaches past the rear-edge ledge, the two interfere
    # and the corner breaks through. Ledge behind the groove = inset - back seat.
    if getattr(spec, "back", None) == BackStyle.GROOVED:
        groove_depth = round(m.carcass * HOUSED_DEPTH_FRACTION, 1)
        rear_ledge = GROOVE_BACK_INSET - m.back   # solid wood behind the back seat
        if groove_depth > rear_ledge:
            issues.append(Issue(
                "warning", "back",
                f"the {groove_depth:.0f}mm-deep back groove on an {m.carcass:.0f}mm "
                f"side reaches past the {max(rear_ledge, 0.0):.0f}mm rear-edge ledge "
                f"(inset {GROOVE_BACK_INSET:.0f}mm - {m.back:.0f}mm back) — the groove "
                "and the rear recess interfere; use a shallower groove, a thinner "
                "back, or rabbet the rear edge for the back"))

    # --- 3) drawer-slide screw line vs. shelf-pin row collision ------------
    # Both land on the side panels in the same bottom-referenced frame; reuse the
    # drilling schedule so the heights match the real bores exactly.
    if getattr(spec, "shelves", 0) > 0 and getattr(spec, "drawers", None):
        try:
            ds = drilling_schedule(spec)
        except Exception as exc:
            # As above: surface the gap rather than skipping the slide-vs-pin
            # collision check silently.
            ds = None
            issues.append(Issue(
                "warning", "drawers",
                "could not verify the drawer-slide vs shelf-pin clearance — the "
                f"drilling schedule failed to build ({type(exc).__name__}); "
                "review the slide and pin layout manually"))
        if ds is not None:
            pin_v: dict[str, list[float]] = {}
            slide_v: dict[str, list[tuple[float, str]]] = {}
            for op in ds.ops:
                if "shelf-pin" in op.operation:
                    pin_v.setdefault(op.part, []).extend(h.v for h in op.holes)
                elif "slide" in op.operation:
                    for h in op.holes:
                        slide_v.setdefault(op.part, []).append((h.v, op.operation))
            seen: set[str] = set()
            for side, lines in slide_v.items():
                pins = pin_v.get(side, [])
                for v, opname in lines:
                    if any(abs(v - pv) < SLIDE_PIN_CLEARANCE for pv in pins):
                        key = f"{side}:{opname}"
                        if key in seen:
                            continue
                        seen.add(key)
                        issues.append(Issue(
                            "warning", "drawers",
                            f"on '{side}' a drawer-slide screw line ({opname}) lands "
                            f"within {SLIDE_PIN_CLEARANCE:.0f}mm of a shelf-pin hole "
                            f"(~{round(v):.0f}mm up) — the pilots collide; shift the "
                            "drawer, skip that pin position, or offset the slide line"))
    return issues


def validate(spec, *, tooling=None) -> ValidationResult:
    """Validate *spec*; when a :class:`~tooling.ShopTooling` inventory is given,
    also flag any joinery the declared tools can't make (advisory)."""
    result = _validate_core(spec)
    if tooling is not None:
        from .tooling import tooling_advisories
        for severity, field_, msg in tooling_advisories(spec, tooling):
            result.issues.append(Issue(severity, field_, msg))
    return result


def _validate_core(spec) -> ValidationResult:
    kind = spec_kind(spec)
    if kind == VOID:
        return _validate_void(spec)
    if kind == GROUP:
        return _validate_project(spec)
    # Every leaf type validates through the furniture registry, which returns a
    # flat list of issues; a new type adds its checks by registering.
    return ValidationResult(furniture.get(kind).validate(spec))


def _check_cabinet_drawers_and_hinges(spec) -> list[Issue]:
    """Drawer slides + box joinery (HW-001/002, STRUCT-011/012) and hinge bores.

    Extracted from :func:`_validate_cabinet` — the single largest check group.
    Self-contained: it re-derives the material and the shared front layout.
    """
    issues: list[Issue] = []
    m = spec.material

    def err(fieldname: str, msg: str) -> None:
        issues.append(Issue("error", fieldname, msg))

    def warn(fieldname: str, msg: str) -> None:
        issues.append(Issue("warning", fieldname, msg))

    # Shared front layout (single source of truth for door/drawer sizing).
    plan = front_plan(spec)

    # --- drawer slides + box joinery (HW-001/002, STRUCT-011, GRAIN-001) -
    boxed = [d for d in spec.drawers if not d.false_front]
    if boxed:
        opening_w = plan.opening_w
        interior_depth = spec.interior_depth

        # Corner joints — dedupe so N identical drawers don't spam N warnings.
        for cj in {d.corner_joint for d in boxed}:
            if cj == CornerJoint.BUTT:
                warn("drawers",
                     "drawer corners use a butt joint (end-grain glue, weak and "
                     "pulls apart when opened); use dovetail, box, or a locking "
                     "rabbet")
            elif cj not in STRONG_DRAWER_JOINTS:
                warn("drawers",
                     f"drawer corner '{cj}' is weak for the pull-open load; "
                     "prefer dovetail, box joint, or a locking rabbet")

        # STRUCT-012: a front dovetail must have its tails on the drawer SIDES
        # so the interlock resists the front being pulled off when opened.
        for tails in {d.dovetail_tails for d in boxed
                      if d.corner_joint == CornerJoint.DOVETAIL}:
            if tails != DovetailTails.SIDES:
                err("drawers",
                    f"dovetail tails are on the '{tails}'; put the tails on the "
                    "drawer sides (pins on the front) so the front can't pull "
                    "off when the drawer is opened")

        # Side-mount slide clearance (HW-001) + resulting box width.
        for clr in {round(d.slide_clearance, 2) for d in boxed
                    if d.slide_type == SlideType.SIDE_MOUNT}:
            if not (10.0 <= clr <= 14.0):
                warn("drawers",
                     f"side-mount slides need ~{SIDE_MOUNT_CLEARANCE:.1f}mm "
                     f"(½in) per side; got {clr:.1f}mm — drawer will bind or rattle")
            box_w = opening_w - 2 * clr
            if box_w <= 0:
                err("drawers",
                    "opening is too narrow for side-mount slides plus a box")
            elif box_w < MIN_DRAWER_BOX_WIDTH:
                warn("drawers",
                     f"drawer box only {box_w:.0f}mm wide after slide clearance; "
                     "barely usable")

        # Slide length vs. cabinet depth (HW-002).
        for sl in {round(d.slide_length, 1) for d in boxed if d.slide_length > 0}:
            if sl > interior_depth:
                err("drawers",
                    f"drawer slide length {sl:.0f}mm exceeds the {interior_depth:.0f}mm "
                    "interior depth; it won't fit")

        # HW-003: depth that wastes a slide size. When the box is auto-sized to
        # the longest standard slide that fits, a deep cabinet may leave enough
        # room for the next 50mm size up — flag it so the depth isn't wasted.
        if any(d.slide_length <= 0 for d in boxed):
            usable = interior_depth - DRAWER_BOX_DEPTH_GAP
            fit = longest_slide_for(usable)
            if fit > 0 and usable - fit > SLIDE_DEPTH_WASTE_MM:
                warn("depth",
                     f"interior depth allows only a {fit:.0f}mm slide but leaves "
                     f"~{usable - fit:.0f}mm unused; a slightly deeper cabinet "
                     "would take the next standard slide size and a deeper box")

    # --- concealed hinge bore vs. door (HW-005) --------------------------
    has_door = spec.doors > 0 or spec.cabinet_type == CabinetType.CORNER_DIAGONAL
    if has_door:
        # A 35mm cup bores 12.5mm deep; the door must host it with backing.
        # Blow-through (A3, depth axis): a cup that leaves less than the minimum
        # backing punches through the door face — a hard error, not a warning.
        backing = m.door - HINGE_CUP_DEPTH
        if backing < HINGE_MIN_DOOR_BACKING:
            err("material.door",
                f"a {m.door:.0f}mm door leaves only {max(backing, 0.0):.1f}mm behind "
                f"a {HINGE_CUP_DEPTH:.1f}mm hinge cup (need ≥{HINGE_MIN_DOOR_BACKING:.0f}"
                "mm) — the 35mm cup blows through the face; use ≥16mm door stock or a "
                "shallower hinge")
        elif m.door < 16.0:
            # Hosts the cup with the minimum backing, but thin stock telegraphs
            # the cup and offers little screw purchase — buildable, worth a note.
            warn("material.door",
                 f"only {backing:.1f}mm of material behind a {HINGE_CUP_DEPTH:.1f}mm "
                 "hinge cup; use ≥16mm door stock for a 35mm concealed hinge")

    if spec.doors > 0 and not spec.is_corner and plan.doors:
        door_w = min(d.width for d in plan.doors)  # narrowest leaf
        if door_w < HINGE_MIN_DOOR_WIDTH:
            err("doors",
                f"each door is only {door_w:.0f}mm wide — too narrow for a 35mm "
                f"hinge cup (needs ≥{HINGE_MIN_DOOR_WIDTH:.0f}mm); use one door, "
                "drop the center mullion, or fit a compact hinge")
        elif door_w < HINGE_MIN_DOOR_WIDTH + 10.0:
            warn("doors",
                 f"each door is {door_w:.0f}mm wide — tight for a 35mm hinge cup; "
                 "consider a wider door or a compact hinge")
    return issues


def _validate_cabinet(spec) -> list[Issue]:
    """Sanity checks for a cabinet (every CabinetType variant)."""
    issues: list[Issue] = []

    def err(fieldname: str, msg: str) -> None:
        issues.append(Issue("error", fieldname, msg))

    def warn(fieldname: str, msg: str) -> None:
        issues.append(Issue("warning", fieldname, msg))

    def info(fieldname: str, msg: str) -> None:
        issues.append(Issue("info", fieldname, msg))

    # --- basic positive, finite, sane dimensions -------------------------
    for name in ("width", "height", "depth"):
        val = getattr(spec, name)
        if not _finite_positive(val):
            err(name, f"must be a positive, finite number, got {val!r}")
        elif val > MAX_DIMENSION:
            err(name, f"exceeds the practical maximum of {MAX_DIMENSION:.0f}mm")

    m = spec.material
    for name in ("carcass", "back", "door", "shelf", "drawer_box"):
        val = getattr(m, name, 18.0)
        if not _finite_positive(val):
            err(f"material.{name}", f"thickness must be positive & finite, got {val!r}")

    # Counts must be sane and bounded (range() over a huge count would hang).
    if not isinstance(spec.shelves, int) or not (0 <= spec.shelves <= MAX_SHELVES):
        err("shelves", f"must be an integer 0–{MAX_SHELVES}, got {spec.shelves!r}")
    if not isinstance(spec.reveal, (int, float)) or not math.isfinite(spec.reveal):
        err("reveal", f"must be a finite number, got {spec.reveal!r}")
    if len(spec.drawers) > MAX_DRAWERS:
        err("drawers", f"too many drawers (max {MAX_DRAWERS})")

    # Stop here if fundamentals are broken — later checks would divide nonsense.
    if any(i.severity == "error" for i in issues):
        return issues

    # --- geometric consistency -------------------------------------------
    if spec.width < 2 * m.carcass + 50:
        err("width", "too narrow to hold two sides plus a usable opening")

    if spec.toe_kick_height >= spec.height:
        err("toe_kick.height", "toe kick is taller than the whole cabinet")
    if spec.toe_kick and spec.toe_kick.setback >= spec.depth:
        err("toe_kick.setback", "toe kick setback exceeds cabinet depth")

    box_height = spec.box_height
    if box_height <= m.carcass * 2:
        err("height", "carcass box height collapses after removing toe kick")

    # --- counts ----------------------------------------------------------
    if spec.doors not in (0, 1, 2):
        err("doors", f"prototype supports 0, 1 or 2 doors, got {spec.doors}")
    if spec.shelves < 0:
        err("shelves", "shelf count cannot be negative")
    if spec.reveal < 0:
        err("reveal", "reveal (gap) cannot be negative")

    # --- fronts must fit the opening height ------------------------------
    drawer_total = sum(d.front_height for d in spec.drawers)
    drawer_total += spec.reveal * max(len(spec.drawers), 0)
    if drawer_total >= box_height:
        err("drawers", "drawer fronts are taller than the available opening")

    # --- soft warnings (buildable, but worth flagging) -------------------
    if spec.doors == 1 and spec.width > 600:
        warn("doors", "a single door wider than 600mm tends to sag; consider two")
    if spec.shelves > 0 and spec.drawers:
        warn("shelves", "shelves above a drawer bank may be obstructed by the box")
    if spec.center_mullion and spec.doors != 2:
        warn("center_mullion", "a center mullion only applies to a pair of doors")

    # --- per cabinet type ------------------------------------------------
    if spec.cabinet_type == CabinetType.WALL:
        if spec.toe_kick is not None:
            warn("toe_kick", "wall cabinets hang on the wall and have no toe kick")
        if spec.drawers:
            warn("drawers", "drawers are unusual in a wall cabinet")
        if spec.depth > 450:
            warn("depth", "wall cabinets are typically 300-400mm deep")
    elif spec.cabinet_type == CabinetType.TALL:
        if spec.toe_kick is None:
            warn("toe_kick", "tall/pantry cabinets usually sit on a toe kick")
        if spec.height < 1500:
            warn("height", "unusually short for a tall/pantry cabinet")
    elif spec.cabinet_type == CabinetType.CORNER_BLIND:
        if spec.blind_width <= 0:
            err("blind_width", "a blind corner needs a positive blind_width")
        elif spec.blind_width >= spec.width - 100:
            err("blind_width", "blind_width leaves no usable door opening")
    elif spec.cabinet_type == CabinetType.CORNER_DIAGONAL:
        if spec.corner_cut <= 0:
            err("corner_cut", "a diagonal corner needs a positive corner_cut")
        elif spec.corner_cut >= min(spec.width, spec.depth):
            err("corner_cut", "corner_cut cannot exceed the cabinet footprint")
    elif spec.cabinet_type == CabinetType.BOOKCASE:
        if spec.doors:
            warn("doors", "a bookcase is open shelving; set doors to 0")
        if spec.shelves == 0:
            warn("shelves", "a bookcase usually has shelves")
        else:
            # Clear height of each shelf bay: the interior split into shelves+1
            # bays, each losing one shelf's thickness. Hardbacks want ~300mm.
            bays = spec.shelves + 1
            bay_clear = (spec.box_height - 2 * m.carcass
                         - spec.shelves * m.shelf) / bays
            if bay_clear < 300:
                warn("shelves",
                     f"~{bay_clear:.0f}mm clear per shelf bay is tight for "
                     "hardbacks (~300mm); use fewer shelves or a taller box "
                     "(paperbacks need ~200mm)")
    elif spec.cabinet_type == CabinetType.DRESSER:
        if not spec.drawers:
            warn("drawers", "a dresser is a drawer bank; add some drawers")
    else:  # BASE
        if spec.depth > 700:
            warn("depth", "unusually deep for a base cabinet")

    # --- shelf deflection / sag (STRUCT-020..022) ------------------------
    # Treat each shelf as a simply-supported beam spanning the interior width.
    if spec.shelves > 0:
        span = spec.width - 2 * m.carcass
        shelf_depth = max(spec.depth - 30.0, 1.0)  # back/clearance setback
        res = engineering.evaluate_shelf(
            span=span,
            depth=shelf_depth,
            thickness=m.shelf,
            load_kg_per_m=getattr(spec, "shelf_load_kg_per_m", 25.0),
            species=getattr(spec, "shelf_species", "plywood"),
        )
        if res.status == "fail":
            err("shelves",
                f"shelf will sag {res.deflection:.1f}mm over a {span:.0f}mm span, "
                f"past the {res.engineering_limit:.1f}mm structural limit "
                "(span/360); shorten span, thicken, stiffen, or add support")
        elif res.status == "visible":
            warn("shelves",
                 f"shelf sag {res.deflection:.1f}mm over {span:.0f}mm will be "
                 f"visible (> {res.visible_limit:.1f}mm); consider a stiffer "
                 "material, thicker shelf, or a center support")

    # --- tip-over stability (STRUCT-030/031, ASTM F2057) -----------------
    if spec.cabinet_type in (CabinetType.DRESSER, CabinetType.TALL):
        if spec.height >= F2057_HEIGHT_MM and not getattr(spec, "anti_tip", False):
            warn("anti_tip",
                 "tall storage unit is in scope for the ASTM F2057 tip-over "
                 "standard; provide an anti-tip restraint and a marked "
                 "wall-attachment point (set anti_tip=true)")
        if engineering.tip_safety_factor(spec.height, spec.depth) < 0.40:
            warn("depth",
                 "tall and shallow: high tip-over risk; deepen the base, lower "
                 "the centre of gravity, or require wall anchoring")

    # --- toe-kick minimum dimensions (STRUCT-042, KCMA A161.1) -----------
    if spec.toe_kick is not None:
        if spec.toe_kick.height < KCMA_TOE_MIN_HEIGHT:
            warn("toe_kick.height",
                 f"toe kick below the ~{KCMA_TOE_MIN_HEIGHT:.0f}mm (3in) KCMA "
                 "minimum height")
        if spec.toe_kick.setback < KCMA_TOE_MIN_SETBACK:
            warn("toe_kick.setback",
                 f"toe space shallower than the ~{KCMA_TOE_MIN_SETBACK:.0f}mm "
                 "(2in) KCMA minimum depth")

    # --- carcass joinery vs. load (STRUCT-010/014) -----------------------
    if spec.joinery == Joinery.BUTT:
        warn("joinery",
             "a glued butt joint is weak in tension/shear for a carcass; use "
             "dado/rabbet/dowel/domino so panels are mechanically captured")

    issues += _check_cabinet_drawers_and_hinges(spec)

    # --- buildable from real stock (MAT-001/002) -------------------------
    box_h = spec.box_height
    interior_w = spec.interior_width
    for name in ("carcass", "back", "door", "shelf"):
        t = getattr(m, name)
        if not stock.is_standard_sheet_thickness(t):
            warn(f"material.{name}",
                 f"{t:.1f}mm is not a stocked sheet thickness; nearest is "
                 f"{stock.nearest_sheet_thickness(t):.0f}mm")
    if not stock.fits_standard_sheet(box_h, max(spec.depth, interior_w)):
        warn("width",
             f"a {box_h:.0f}×{max(spec.depth, interior_w):.0f}mm panel exceeds a "
             "standard 2440×1220 sheet; seam, use an oversize sheet, or resize")

    # --- 32mm system shelf-pin drilling feasibility (DIM-009) ------------
    if spec.shelves > 0:
        column = box_h - 2 * PIN_END_MARGIN
        positions = int(column // SYSTEM_PITCH) + 1 if column >= 0 else 0
        if positions < MIN_PIN_POSITIONS:
            warn("shelves",
                 f"interior is too short to drill a 32mm-system shelf-pin column "
                 f"({positions} pin position(s)); adjustable shelves need a taller "
                 "box or a tighter end margin")
        if spec.depth < 2 * ROW_SETBACK + 10.0:
            warn("depth",
                 "too shallow for two 32mm-system shelf-pin rows "
                 f"(need >~{2 * ROW_SETBACK:.0f}mm of depth); the rows would collide")

    # --- proportion advisories (PROP-001/003, INFO) ----------------------
    # Front face: how the piece reads head-on. Corner cabinets have an
    # irregular face, so skip them.
    if not spec.is_corner:
        face = proportion.ratio_of(spec.width, box_h)
        if proportion.is_awkward(face):
            longer, shorter = max(spec.width, box_h), min(spec.width, box_h)
            tall_target, short_target = proportion.golden_targets(longer, shorter)
            info("proportion",
                 f"front face {spec.width:.0f}×{box_h:.0f}mm reads as {face:.2f}:1; "
                 f"the golden ratio (1.62:1) is more balanced — e.g. shorten the "
                 f"long side to {short_target:.0f}mm or extend the short side to "
                 f"{tall_target:.0f}mm")
    drawer_heights = [d.front_height for d in spec.drawers]
    if len(drawer_heights) >= 3 and not proportion.is_well_graduated(drawer_heights):
        info("drawers",
             "drawer heights are irregular; a uniform or graduated bank "
             "(shorter drawers on top, taller toward the bottom) looks more "
             "intentional")

    # --- A3 joinery / machining feasibility (analytic, no CAD) -----------
    issues.extend(joinery_feasibility(spec))

    # --- accessories: countertop, appliance cutout, filler, molding ------
    if getattr(spec, "accessories", None):
        from .accessories import accessory_issues
        for severity, field_, msg in accessory_issues(spec):
            issues.append(Issue(severity, field_, msg))

    # --- material-specific build hints (when form/species are declared) --
    from .materials import build_hints
    for severity, field_, msg in build_hints(spec):
        issues.append(Issue(severity, field_, msg))

    return issues


# Backwards-compatible private alias (promoted to public API).
_joinery_feasibility = joinery_feasibility


# Register the built-in leaf validators. Each returns a flat ``list[Issue]``; a
# new furniture type registers its own ``validate`` and routes with no edit to
# ``_validate_core``.
furniture.register(CABINET, validate=_validate_cabinet)
furniture.register(TABLE, validate=lambda spec: _validate_table(spec).issues)
