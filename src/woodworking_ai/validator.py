"""Deterministic validation of a cabinet spec.

This is *not* an LLM. It applies type/range checks plus woodworking sanity
rules, catching the great majority of design errors before we ever attempt
geometry. It returns structured issues so the designer agent can self-repair.

No CAD dependency — runs anywhere, instantly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .dsl import TableSpec, ComponentGroup, CabinetType, Joinery
from . import engineering, stock, proportion
from .hardware import longest_slide_for
from .geometry import front_plan, footprints_overlap, component_tag

# ASTM F2057 scope: clothing storage units >= 27in (686mm) tall fall under the
# CPSC tip-over standard. Toe-kick minimums per ANSI/KCMA A161.1 (2in x 3in).
F2057_HEIGHT_MM = 686.0
KCMA_TOE_MIN_HEIGHT = 75.0   # ~3 in
KCMA_TOE_MIN_SETBACK = 50.0  # ~2 in deep

SIDE_MOUNT_CLEARANCE = 12.7  # ½in nominal per-side gap for side-mount slides
MIN_DRAWER_BOX_WIDTH = 150.0 # below this a box is barely usable
DRAWER_BOX_DEPTH_GAP = 25.0  # box shallower than the interior (matches cutlist)
# Depth left unused beyond the largest fitting standard slide before it's worth
# flagging: a deeper cabinet could take the next 50mm slide size.
SLIDE_DEPTH_WASTE_MM = 60.0

# 35mm concealed (Euro) hinge cup geometry (matches drilling.py).
HINGE_CUP_DIA = 35.0
HINGE_CUP_DEPTH = 12.5
HINGE_CUP_INSET = 22.5       # cup centre in from the door's hinge edge
# Cup outer edge reaches INSET + DIA/2 from the hinge edge; the door must be at
# least this wide to host the bore, plus a little material for strength.
HINGE_MIN_DOOR_WIDTH = HINGE_CUP_INSET + HINGE_CUP_DIA / 2  # 40mm hard minimum
HINGE_MIN_DOOR_BACKING = 3.0  # material left behind the cup

# Drawer-corner joints that properly resist the pull-apart load of opening.
STRONG_DRAWER_JOINTS = {"dovetail", "box", "rabbet", "locking_rabbet"}

# 32mm System constants (match drilling.py) for the grid feasibility check.
SYSTEM_PITCH = 32.0
PIN_END_MARGIN = 64.0        # first/last system hole in from the panel ends
ROW_SETBACK = 37.0           # each pin row in from the front / back edge
MIN_PIN_POSITIONS = 3        # fewer than this is not meaningfully adjustable

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
            spec.depth, getattr(spec, "grain", "flatsawn"))
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
    joint = str(getattr(spec, "joinery", "mortise_tenon")).strip().lower()
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


def validate(spec) -> ValidationResult:
    if isinstance(spec, ComponentGroup):
        return _validate_project(spec)
    if isinstance(spec, TableSpec):
        return _validate_table(spec)
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
        return ValidationResult(issues)

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

    # Shared front layout (single source of truth for door/drawer sizing).
    plan = front_plan(spec)

    # --- drawer slides + box joinery (HW-001/002, STRUCT-011, GRAIN-001) -
    boxed = [d for d in spec.drawers if not d.false_front]
    if boxed:
        opening_w = plan.opening_w
        interior_depth = spec.interior_depth

        # Corner joints — dedupe so N identical drawers don't spam N warnings.
        for cj in {str(d.corner_joint).strip().lower() for d in boxed}:
            if cj == "butt":
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
        for tails in {str(d.dovetail_tails).strip().lower() for d in boxed
                      if str(d.corner_joint).strip().lower() == "dovetail"}:
            if tails not in ("sides", "side"):
                err("drawers",
                    f"dovetail tails are on the '{tails}'; put the tails on the "
                    "drawer sides (pins on the front) so the front can't pull "
                    "off when the drawer is opened")

        # Side-mount slide clearance (HW-001) + resulting box width.
        for clr in {round(d.slide_clearance, 2) for d in boxed
                    if str(d.slide_type).strip().lower() == "side_mount"}:
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
        if m.door <= HINGE_CUP_DEPTH:
            err("material.door",
                f"a {m.door:.0f}mm door is thinner than the {HINGE_CUP_DEPTH:.1f}mm "
                "hinge cup; a 35mm concealed hinge cannot be bored — thicken the "
                "door or change hinge")
        elif m.door < HINGE_CUP_DEPTH + HINGE_MIN_DOOR_BACKING:
            warn("material.door",
                 f"only {m.door - HINGE_CUP_DEPTH:.1f}mm of material behind a "
                 f"{HINGE_CUP_DEPTH:.1f}mm hinge cup; use ≥16mm door stock for a "
                 "35mm concealed hinge")

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

    # --- accessories: countertop, appliance cutout, filler, molding ------
    if getattr(spec, "accessories", None):
        from .accessories import accessory_issues
        for severity, field_, msg in accessory_issues(spec):
            issues.append(Issue(severity, field_, msg))

    # --- material-specific build hints (when form/species are declared) --
    from .materials import build_hints
    for severity, field_, msg in build_hints(spec):
        issues.append(Issue(severity, field_, msg))

    return ValidationResult(issues)
