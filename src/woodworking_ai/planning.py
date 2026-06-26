"""Build plan: skill rating + realistic, method-aware build time.

The estimator's labour model is a flat rate (base + per-part + per-door +
per-drawer). It can't tell that **hand-cut dovetails take many times longer than
a Domino**, and it gives no difficulty signal. Now that the tooling inventory
(:mod:`woodworking_ai.tooling`) knows *which tool makes each joint*, time can be
derived from the **method the shop would actually use** — hand vs. jig vs.
machine.

Two pure-math functions live here, both no-CAD and explainable:

* :func:`skill` — ``{level, drivers}``: a beginner/intermediate/advanced rating
  derived from joinery (hand dovetails / mortise-and-tenon ⇒ advanced), part
  count, glue-up count, finishing, and the number of fronts/drawers, with the
  specific reasons listed.
* :func:`build_time` — ``{hours_by_phase, total, drivers}``: walks every
  operation the spec requires (:func:`tooling.required_operations`), picks the
  **method** the shop would use for each (:func:`_method_for`), and applies a
  per-``(operation, method)`` time table where *hand ≫ jig ≫ machine*. Phases:
  mill, joinery, assembly, finish, hardware. When no tooling is supplied it
  assumes a reasonable default method, so the no-tooling path is stable.

Nothing here mutates the spec or depends on the cut list internals beyond a part
count; it is safe to call on a cabinet, a table, or a whole project/assembly.
"""

from __future__ import annotations

import logging

from .dispatch import (spec_kind, VOID, GROUP, TABLE, CABINET,
                       BENCH, NIGHTSTAND, DESK, WORKBENCH)
from .tooling import (
    JOINT_WAYS, ShopTooling, Requirement, required_operations, _norm,
)

log = logging.getLogger(__name__)

# ===========================================================================
# Method model — which *kind* of tool makes a joint, and how slow each is.
# ===========================================================================
#
# Every capability in a JOINT_WAYS "way" is bucketed into one of three methods.
# A way's method is the *fastest* bucket any of its required capabilities map to
# (a way that uses only hand tools is "hand"; one that uses a router is
# "machine"). The build-time table is then keyed by (operation, method), so the
# same dado costs ~5x more cut by hand than ploughed on the table saw.

HAND = "hand"
JIG = "jig"
MACHINE = "machine"

# Capability -> method bucket. Anything not listed is treated as a machine.
_CAP_METHOD: dict[str, str] = {
    "hand_tools": HAND,
    # jigs / guided specialty tools (faster than hand, slower than a dedicated
    # machine setup) ------------------------------------------------------------
    "doweling_jig": JIG,
    "pocket_jig": JIG,
    "biscuit_joiner": JIG,
    "dovetail_jig": JIG,
    "box_joint_jig": JIG,
    "domino": JIG,
    "shelf_pin_jig": JIG,
    # stationary / powered machines --------------------------------------------
    "table_saw": MACHINE,
    "dado_set": MACHINE,
    "router": MACHINE,
    "router_table": MACHINE,
    "band_saw": MACHINE,
    "drill": MACHINE,
    "drill_press": MACHINE,
    "jointer": MACHINE,
    "planer": MACHINE,
    "mortiser": MACHINE,
    "forstner_35": MACHINE,
}

_METHOD_RANK = {MACHINE: 0, JIG: 1, HAND: 2}   # lower = faster/preferred


def _way_method(way: tuple) -> str:
    """The method bucket for one JOINT_WAYS 'way' (a tuple of capabilities).

    An empty way (glue/clamps only) is hand work. Otherwise the way's method is
    the *fastest* bucket among its capabilities — owning a router makes a dado a
    machine operation even though hand tools could also cut it.
    """
    if not way:
        return HAND
    return min((_CAP_METHOD.get(c, MACHINE) for c in way),
               key=lambda m: _METHOD_RANK[m])


def _method_for(joint: str, tooling: ShopTooling | None) -> str:
    """The method the shop would actually use to make *joint*.

    With a *tooling* inventory: the fastest method among the ways the shop can
    actually make (mirrors :func:`tooling.can_make` — owning the caps of a way
    enables it). When the shop owns *no* way (it can't make the joint at all) we
    fall back to the hand method, the universal last resort and the slowest, so
    an infeasible-but-attempted joint reads as expensive rather than free.

    With no inventory (*tooling* is ``None``): the fastest method any defined way
    offers — a reasonable, well-equipped-shop default that keeps the no-tooling
    path stable and cheap.
    """
    ways = JOINT_WAYS.get(_norm(joint))
    if not ways:
        return MACHINE          # unknown op: treat as a quick machine pass
    if tooling is None:
        methods = [_way_method(w) for w in ways]
    else:
        methods = [_way_method(w) for w in ways
                   if all(tooling.has(c) for c in w)]
        if not methods:        # can't make it at all -> assume the hand fallback
            return HAND
    return min(methods, key=lambda m: _METHOD_RANK[m])


# ===========================================================================
# Time tables (hours). Hand >> jig >> machine for the same operation.
# ===========================================================================
#
# Each entry is hours for ONE instance of the operation by that method. These
# are deliberately round, explainable shop numbers — a quote starting point, not
# a stopwatch. The phase each operation rolls up into is in _OP_PHASE.

# (operation, method) -> hours. Operations are JOINT_WAYS keys.
_OP_TIME: dict[str, dict[str, float]] = {
    # carcass / case joinery ---------------------------------------------------
    "dado":           {MACHINE: 0.15, JIG: 0.25, HAND: 0.80},
    "rabbet":         {MACHINE: 0.12, JIG: 0.20, HAND: 0.60},
    "groove":         {MACHINE: 0.12, JIG: 0.20, HAND: 0.60},
    "locking_rabbet": {MACHINE: 0.25, JIG: 0.35, HAND: 1.00},
    "butt":           {MACHINE: 0.05, JIG: 0.05, HAND: 0.10},
    # loose-tenon / dowel / mechanical -----------------------------------------
    "dowel":          {MACHINE: 0.20, JIG: 0.25, HAND: 0.50},
    "domino":         {MACHINE: 0.15, JIG: 0.15, HAND: 0.50},
    "biscuit":        {MACHINE: 0.12, JIG: 0.15, HAND: 0.40},
    "pocket":         {MACHINE: 0.10, JIG: 0.12, HAND: 0.30},
    "screw":          {MACHINE: 0.08, JIG: 0.10, HAND: 0.15},
    # the hard, advanced joinery — where hand work dominates -------------------
    "mortise_tenon":  {MACHINE: 0.40, JIG: 0.55, HAND: 1.80},
    "dovetail":       {MACHINE: 0.50, JIG: 0.70, HAND: 2.20},
    "box":            {MACHINE: 0.30, JIG: 0.40, HAND: 1.20},
    # 5-piece door frames ------------------------------------------------------
    "cope_stick":     {MACHINE: 0.40, JIG: 0.50, HAND: 1.50},
    # boring -------------------------------------------------------------------
    "hinge_cup":      {MACHINE: 0.10, JIG: 0.15, HAND: 0.30},
    "shelf_pins":     {MACHINE: 0.15, JIG: 0.20, HAND: 0.45},
}
_OP_TIME_DEFAULT = {MACHINE: 0.15, JIG: 0.25, HAND: 0.60}

# Which phase each operation rolls up into.
_BORING_OPS = {"hinge_cup", "shelf_pins"}


def _op_phase(role: str, joint: str) -> str:
    """Phase bucket for a required operation: 'hardware' for boring, else
    'joinery'. Boring (hinge cups, shelf-pin rows) is hardware-fitting work."""
    if role == "boring" or _norm(joint) in _BORING_OPS:
        return "hardware"
    return "joinery"


# ===========================================================================
# Skill rating.
# ===========================================================================

# Joints that mark a build as advanced when cut by hand-tool-level joinery.
_ADVANCED_JOINTS = {"dovetail", "mortise_tenon"}
# Joinery that, regardless of method, signals at least intermediate work.
_INTERMEDIATE_JOINTS = {"dado", "rabbet", "groove", "box", "cope_stick",
                        "locking_rabbet", "domino", "biscuit"}


def _part_count(spec) -> int:
    """Total parts in the cut list (recurses through groups). 0 if unbuildable."""
    try:
        from .cutlist import generate_cutlist
        cl = generate_cutlist(spec)
        return sum(p.qty for p in cl.parts)
    except Exception:
        log.warning("plan: cut list failed; counting 0 parts", exc_info=True)
        return 0


def glue_up_count(spec) -> int:
    """How many glue-ups the build involves — a key difficulty driver.

    Counts the carcass case glue-up, each non-false drawer box, a solid-wood
    (glue_up) panel carcass, and a table's top/apron assembly. Recurses through
    a project/assembly. Rough but explainable.
    """
    kind = spec_kind(spec)
    if kind == VOID:
        return 0
    if kind == GROUP:
        return sum(glue_up_count(c.spec) for c in spec.components)
    if kind == TABLE:
        return 1   # the leg/apron/top assembly
    if kind == WORKBENCH:
        # The base assembly plus a thick top laminated from many strips on edge —
        # a multi-stage glue-up that is the bench's biggest single time sink.
        return 1 + max(1, int(getattr(spec, "lamination_count", 1)))
    # A cabinet (and, by fall-through, the other leaf furniture types).
    n = 1          # the carcass case / base
    if str(getattr(spec, "panel_construction", "sheet")).lower() == "glue_up":
        n += 1     # edge-gluing solid stock into panels
    # ``drawers`` is a list of Drawer on a cabinet but a plain count on the
    # legged types (nightstand/desk); each non-false drawer box is a glue-up.
    drawers = getattr(spec, "drawers", []) or []
    if isinstance(drawers, int):
        n += drawers
    else:
        for dr in drawers:
            if not getattr(dr, "false_front", False):
                n += 1
    return n


def _front_count(spec) -> int:
    """Doors + drawer fronts across the spec (recurses through groups)."""
    kind = spec_kind(spec)
    if kind == GROUP:
        return sum(_front_count(c.spec) for c in spec.components)
    if kind in (VOID, TABLE):
        return 0
    drawers = getattr(spec, "drawers", []) or []
    n_drawers = drawers if isinstance(drawers, int) else len(drawers)
    return int(getattr(spec, "doors", 0) or 0) + n_drawers


def skill(spec) -> dict:
    """Skill rating for *spec*: ``{level, drivers}``.

    ``level`` is one of ``"beginner"``, ``"intermediate"``, ``"advanced"``.
    ``drivers`` lists the specific reasons (e.g. "hand-cut dovetail joinery",
    "12 parts", "3 glue-ups") so the rating is explainable, never a bare label.

    Advanced is driven by hard joinery (dovetails, mortise-and-tenon), a high
    part count, or many glue-ups; finishing and many fronts nudge a build up from
    beginner. Pure inspection — works on a cabinet, table, or whole project.
    """
    drivers: list[str] = []
    score = 0

    # Joinery is the dominant signal.
    joints = {_norm(r.joint) for r in _safe_reqs(spec)}
    advanced_joints = sorted(joints & _ADVANCED_JOINTS)
    inter_joints = sorted(joints & _INTERMEDIATE_JOINTS)
    if advanced_joints:
        score += 3
        pretty = ", ".join(j.replace("_", "-") for j in advanced_joints)
        drivers.append(f"{pretty} joinery")
    elif inter_joints:
        score += 1
        drivers.append("machined case joinery (dado/rabbet/etc.)")

    parts = _part_count(spec)
    if parts >= 30:
        score += 2
        drivers.append(f"{parts} parts (large build)")
    elif parts >= 12:
        score += 1
        drivers.append(f"{parts} parts")

    glue_ups = glue_up_count(spec)
    if glue_ups >= 4:
        score += 2
        drivers.append(f"{glue_ups} glue-ups")
    elif glue_ups >= 2:
        score += 1
        drivers.append(f"{glue_ups} glue-ups")

    fronts = _front_count(spec)
    if fronts >= 6:
        score += 1
        drivers.append(f"{fronts} fronts to fit and align")

    if str(getattr(spec, "finish", "none")).lower() != "none":
        score += 1
        drivers.append(f"a {spec.finish} finish to apply")

    if score >= 4:
        level = "advanced"
    elif score >= 2:
        level = "intermediate"
    else:
        level = "beginner"
    if not drivers:
        drivers.append("simple parts, screwed/butt joinery, no finish")
    return {"level": level, "drivers": drivers}


def _safe_reqs(spec) -> list[Requirement]:
    try:
        return required_operations(spec)
    except Exception:
        log.warning("plan: required_operations failed; no joinery requirements",
                    exc_info=True)
        return []


# ===========================================================================
# Method-aware build time.
# ===========================================================================

_PHASES = ("mill", "joinery", "assembly", "finish", "hardware")

# Stock prep (milling) per part, by method. With a jointer+planer (machine) it's
# quick; by hand-plane it's slow bench work. Sheet-goods shops skip much of this.
_MILL_PER_PART = {MACHINE: 0.05, JIG: 0.08, HAND: 0.20}
# Assembly / glue-up per glue-up (dry-fit, glue, clamp, check square).
_ASSEMBLY_PER_GLUEUP = 0.5
# Finish per coat per part-ish unit (sanding + a coat); flat, method-agnostic.
_FINISH_PER_FRONT = 0.25
_FINISH_BASE = 0.5
# Hardware fitting (hinges, pulls, slides) per front, on top of any boring.
_HARDWARE_PER_FRONT = 0.2


def _mill_method(tooling: ShopTooling | None) -> str:
    """Method used for stock prep: machine if a jointer/planer is owned, else
    hand. With no inventory, assume the machine path (well-equipped default)."""
    if tooling is None:
        return MACHINE
    if tooling.has("jointer") or tooling.has("planer"):
        return MACHINE
    return HAND


def _is_solid_stock(spec) -> bool:
    """True when the piece is milled from solid lumber (so stock prep matters).

    Sheet-goods carcasses arrive flat and need little milling; a solid table or
    a glue_up panel cabinet needs jointing/planing per part.
    """
    kind = spec_kind(spec)
    # Any piece explicitly milled from solid lumber needs real stock prep. This
    # catches the solid-by-default leaf types (workbench/bench/frame/box/board/
    # bed) whose material_form is "solid".
    if str(getattr(spec, "material_form", "")).lower() == "solid":
        return True
    if kind in (TABLE, BENCH, NIGHTSTAND, DESK, WORKBENCH):
        # Legged pieces with a solid top (the default) are milled from lumber.
        return bool(getattr(spec, "solid_top", True))
    if kind == CABINET:
        if str(getattr(spec, "panel_construction", "sheet")).lower() == "glue_up":
            return True
        return str(getattr(spec, "material_form", "")).lower() == "solid"
    return False


def build_time(spec, tooling: ShopTooling | None = None) -> dict:
    """Method-aware build-time estimate for *spec*.

    Returns ``{hours_by_phase: {mill, joinery, assembly, finish, hardware},
    total, drivers}``. For each required operation the *method* the shop would
    use is chosen (:func:`_method_for`) and a per-``(operation, method)`` time is
    applied, where hand work costs far more than a jig or a machine. When
    *tooling* is ``None`` a reasonable well-equipped default method is assumed,
    so the result is stable without an inventory.

    A project/assembly recurses and its phase times sum. ``drivers`` names the
    biggest time sinks so the number is explainable.
    """
    kind = spec_kind(spec)
    phases = {p: 0.0 for p in _PHASES}

    if kind == VOID:
        return {"hours_by_phase": phases, "total": 0.0,
                "drivers": ["a reserved gap — nothing to build"]}

    if kind == GROUP:
        for comp in spec.components:
            sub = build_time(comp.spec, tooling)
            for p in _PHASES:
                phases[p] += sub["hours_by_phase"][p]
        total = sum(phases.values())
        return {"hours_by_phase": _round(phases), "total": round(total, 2),
                "drivers": _phase_drivers(phases)}

    # A leaf (cabinet or table). --------------------------------------------
    # 1. Joinery + boring, per required operation, by the method actually used.
    op_hours: dict[tuple[str, str], float] = {}
    for r in _safe_reqs(spec):
        method = _method_for(r.joint, tooling)
        table = _OP_TIME.get(_norm(r.joint), _OP_TIME_DEFAULT)
        hrs = table.get(method, _OP_TIME_DEFAULT[method])
        phases[_op_phase(r.role, r.joint)] += hrs
        key = (_norm(r.joint), method)
        op_hours[key] = op_hours.get(key, 0.0) + hrs

    # 2. Milling: solid stock needs real prep; sheet goods get a token pass.
    parts = _part_count(spec)
    if _is_solid_stock(spec):
        method = _mill_method(tooling)
        phases["mill"] += parts * _MILL_PER_PART[method]
    else:
        phases["mill"] += parts * 0.02   # cut sheets to rough size

    # 3. Assembly / glue-ups.
    glue_ups = glue_up_count(spec)
    phases["assembly"] += glue_ups * _ASSEMBLY_PER_GLUEUP

    # 4. Finishing (only when a finish is specified).
    if str(getattr(spec, "finish", "none")).lower() != "none":
        fronts = _front_count(spec)
        phases["finish"] += _FINISH_BASE + max(1, fronts) * _FINISH_PER_FRONT

    # 5. Hardware fitting for fronts (hinges/pulls/slides), beyond boring.
    phases["hardware"] += _front_count(spec) * _HARDWARE_PER_FRONT

    total = sum(phases.values())
    return {"hours_by_phase": _round(phases), "total": round(total, 2),
            "drivers": _build_drivers(op_hours, phases)}


def _round(phases: dict) -> dict:
    return {k: round(v, 2) for k, v in phases.items()}


def _phase_drivers(phases: dict) -> list[str]:
    """Name the heaviest phases (used for groups)."""
    ranked = sorted(phases.items(), key=lambda kv: kv[1], reverse=True)
    return [f"{name}: {hrs:.1f} h" for name, hrs in ranked if hrs > 0][:3] \
        or ["nothing to build"]


def _build_drivers(op_hours: dict, phases: dict) -> list[str]:
    """The most time-consuming operations + the dominant phase, in words."""
    out: list[str] = []
    ranked = sorted(op_hours.items(), key=lambda kv: kv[1], reverse=True)
    for (joint, method), hrs in ranked[:2]:
        if hrs <= 0:
            continue
        out.append(f"{joint.replace('_', '-')} ({method}): {hrs:.2f} h")
    heaviest = max(phases.items(), key=lambda kv: kv[1], default=(None, 0))
    if heaviest[0] and heaviest[1] > 0:
        out.append(f"heaviest phase: {heaviest[0]} ({heaviest[1]:.1f} h)")
    return out or ["minimal build time"]


def plan(spec, tooling: ShopTooling | None = None) -> dict:
    """The combined build plan: ``{skill, time}`` — the section the service
    adds to its bundle and the CLI prints. Both halves are pure math."""
    return {"skill": skill(spec), "time": build_time(spec, tooling)}
