"""Shop tool table — what the machines in the shop can actually do.

The Critic uses this to check a design is *machinable*: a dado the dado stack
can cut, a hinge cup a Forstner bit can bore, a box shallow enough to line-bore
by hand. Pure data; a shop can tune it (e.g. wider dado stack, CNC reach).

Two layers live here:

* :class:`ToolTable` — the *dimensional* limits of the machines (kerf, dado
  width, bit sizes). Used by the Critic's machinability check.
* :class:`ShopTooling` — the *inventory* of which tools you actually own, so a
  design only calls for joinery you can make. "I have a table saw, a router and
  a pocket-hole jig but no Domino" → the validator flags any Domino joint and
  suggests a feasible substitute, and the AI designer is told to use only the
  joints you can cut. This is the "design against my tooling" layer.

Both are pure data — no CAD — so they round-trip to JSON and a shop can save
them in a profile.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass
class ToolTable:
    saw_kerf: float = 3.0
    dado_min: float = 6.0          # narrowest a dado stack reliably cuts
    dado_max: float = 20.0         # widest single-setup dado stack
    # Straight router-bit diameters on hand (mm) — used for wider housings.
    router_bits: tuple = (6.0, 8.0, 10.0, 12.0, 12.7)
    forstner_sizes: tuple = (15.0, 20.0, 25.0, 35.0)   # incl. 35mm hinge cup
    max_handdrill_reach: float = 600.0   # depth a hand drill comfortably reaches


DEFAULT_TOOLS = ToolTable()


# ===========================================================================
# Shop tooling inventory — "design against the tools I actually own".
# ===========================================================================

@dataclass
class ShopTooling:
    """What tools the shop owns, as capability flags.

    Each field is a tool/capability you either have (``True``) or don't
    (``False``). The joinery a design uses is checked against these so a plan
    only asks for cuts you can make; when a joint isn't makeable, a feasible
    substitute is suggested. ``hand_tools`` covers a backsaw, chisels and a
    marking gauge — enough to cut traditional joinery (dados, rabbets,
    dovetails, mortise-and-tenon) by hand, slowly. Power tools and jigs are
    each their own flag.

    The defaults describe a *well-equipped* shop (everything on) so an existing
    design that declares no tooling is never constrained — backwards
    compatible. Turn off what you don't own, or start from a preset
    (:data:`HAND_TOOL_SHOP`, :data:`HOBBYIST_SHOP`).
    """

    # --- hand tools (a saw, chisels, a plane) --------------------------------
    hand_tools: bool = True
    # --- stationary / portable power -----------------------------------------
    table_saw: bool = True
    dado_set: bool = True          # a dado stack for housings (needs a saw)
    router: bool = True            # handheld/table router + straight bits
    router_table: bool = True      # cope-and-stick rail-and-stile work
    band_saw: bool = True
    drill: bool = True             # a cordless/corded hand drill
    drill_press: bool = True
    jointer: bool = True           # stock prep: flatten a face/edge
    planer: bool = True            # stock prep: dimension to thickness
    # --- joinery jigs / specialty --------------------------------------------
    doweling_jig: bool = True
    pocket_jig: bool = True         # Kreg-style pocket holes
    domino: bool = False            # Festool Domino (loose tenon) — pricey
    biscuit_joiner: bool = False
    dovetail_jig: bool = False
    box_joint_jig: bool = False
    mortiser: bool = False          # hollow-chisel / slot mortiser
    # --- boring --------------------------------------------------------------
    shelf_pin_jig: bool = True      # 5mm/32mm shelf-pin row jig
    forstner_35: bool = True        # 35mm Forstner for concealed-hinge cups

    # ---- helpers ------------------------------------------------------------

    def has(self, capability: str) -> bool:
        return bool(getattr(self, capability, False))

    def owned(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name)]

    def missing(self) -> list[str]:
        return [f.name for f in fields(self) if not getattr(self, f.name)]

    # ---- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        return {f.name: bool(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data) -> "ShopTooling":
        t = cls()
        if not isinstance(data, dict):
            return t
        for f in fields(t):
            if f.name in data:
                setattr(t, f.name, bool(data[f.name]))
        return t

    @classmethod
    def from_names(cls, names, *, base_off: bool = True) -> "ShopTooling":
        """Build an inventory from a list of owned-capability names.

        With ``base_off`` (default) every tool starts *off* and only the named
        ones are turned on — the natural "here is exactly what I own" form.
        Unknown names are ignored. ``hand_tools`` is always included unless the
        caller explicitly lists tools and omits it *and* passes it as off.
        """
        valid = {f.name for f in fields(cls)}
        t = cls(**{f.name: (not base_off) for f in fields(cls)}) if base_off else cls()
        for n in names or []:
            key = str(n).strip().lower().replace("-", "_").replace(" ", "_")
            if key in valid:
                setattr(t, key, True)
        return t


def tooling_to_dict(t: "ShopTooling | None"):
    return t.to_dict() if isinstance(t, ShopTooling) else None


def tooling_from_dict(data) -> "ShopTooling | None":
    return ShopTooling.from_dict(data) if isinstance(data, dict) else None


# Presets a hobbyist can start from. -----------------------------------------
FULL_SHOP = ShopTooling(domino=True, biscuit_joiner=True, dovetail_jig=True,
                        box_joint_jig=True, mortiser=True)

#: A bench woodworker: hand tools + a drill, nothing else.
HAND_TOOL_SHOP = ShopTooling.from_names(["hand_tools", "drill"])

#: A typical home shop: table saw, router, drill press, dado set, pocket &
#: doweling jigs and a shelf-pin jig — but no Domino/dovetail/box jigs.
HOBBYIST_SHOP = ShopTooling.from_names([
    "hand_tools", "table_saw", "dado_set", "router", "band_saw", "drill",
    "drill_press", "jointer", "planer", "doweling_jig", "pocket_jig",
    "shelf_pin_jig", "forstner_35",
])

PRESETS = {"full": FULL_SHOP, "hobbyist": HOBBYIST_SHOP, "hand": HAND_TOOL_SHOP}


# Human label for each capability. ------------------------------------------
CAP_LABEL = {
    "hand_tools": "hand tools (saw & chisels)", "table_saw": "a table saw",
    "dado_set": "a dado set", "router": "a router",
    "router_table": "a router table", "band_saw": "a band saw",
    "drill": "a drill", "drill_press": "a drill press",
    "jointer": "a jointer", "planer": "a planer",
    "doweling_jig": "a doweling jig", "pocket_jig": "a pocket-hole jig",
    "domino": "a Festool Domino", "biscuit_joiner": "a biscuit joiner",
    "dovetail_jig": "a dovetail jig", "box_joint_jig": "a box-joint jig",
    "mortiser": "a mortiser", "shelf_pin_jig": "a shelf-pin jig",
    "forstner_35": "a 35mm Forstner bit",
}

# How each joint/operation reads in a sentence. ------------------------------
JOINT_LABEL = {
    "dado": "a dado joint", "rabbet": "a rabbet joint", "groove": "a groove",
    "dowel": "dowel joints", "domino": "Domino (loose-tenon) joints",
    "pocket": "pocket-screw joints", "screw": "screwed joints",
    "butt": "a glued butt joint", "mortise_tenon": "mortise-and-tenon joints",
    "dovetail": "dovetail joints", "box": "box / finger joints",
    "locking_rabbet": "a locking-rabbet joint", "biscuit": "biscuit joints",
    "cope_stick": "cope-and-stick (5-piece) doors",
    "hinge_cup": "35mm concealed-hinge cups", "shelf_pins": "shelf-pin holes",
}

# Each joint/operation → the ways it can be made. A way is a tuple of
# capabilities that must ALL be owned; owning the caps of ANY one way makes the
# joint. An empty tuple () means "no special tool needed" (glue/clamps only).
JOINT_WAYS: dict[str, list[tuple]] = {
    "dado":           [("dado_set",), ("router",), ("hand_tools",)],
    "rabbet":         [("dado_set",), ("router",), ("table_saw",), ("hand_tools",)],
    "groove":         [("dado_set",), ("router",), ("table_saw",), ("hand_tools",)],
    "dowel":          [("doweling_jig",), ("drill_press",)],
    "domino":         [("domino",)],
    "biscuit":        [("biscuit_joiner",)],
    "pocket":         [("pocket_jig",)],
    "screw":          [("drill",)],
    "butt":           [()],
    "mortise_tenon":  [("mortiser",), ("router",), ("hand_tools",)],
    "dovetail":       [("dovetail_jig",), ("hand_tools",)],
    "box":            [("box_joint_jig",), ("table_saw",), ("hand_tools",)],
    "locking_rabbet": [("dado_set",), ("router",)],
    "cope_stick":     [("router_table",), ("router",)],
    "hinge_cup":      [("forstner_35",), ("drill_press",)],
    "shelf_pins":     [("shelf_pin_jig",), ("drill_press",), ("drill",)],
}

# When a joint can't be made, what to switch to — by the role it plays.
# Ordered best → fallback; the first feasible one is suggested.
ROLE_PREFERENCE = {
    "carcass": ["dado", "rabbet", "domino", "biscuit", "dowel", "pocket",
                "screw", "butt"],
    "drawer":  ["dovetail", "box", "locking_rabbet", "rabbet", "dowel",
                "pocket", "butt"],
    "frame":   ["mortise_tenon", "domino", "dowel", "pocket", "screw"],
}


def _norm(joint) -> str:
    return str(joint).strip().lower().replace("-", "_").replace(" ", "_")


def requirement_text(joint: str) -> str:
    """Human "needs a router, a dado set, or hand tools" for a joint."""
    ways = JOINT_WAYS.get(_norm(joint))
    if not ways:
        return ""
    parts = []
    for way in ways:
        if not way:                       # glue only
            return "glue and clamps"
        parts.append(" + ".join(CAP_LABEL.get(c, c) for c in way))
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + (", or " if len(parts) > 2 else " or ") + parts[-1]


def can_make(joint: str, tooling: ShopTooling) -> bool:
    """True if *tooling* can produce *joint* (unknown joints pass — don't block)."""
    ways = JOINT_WAYS.get(_norm(joint))
    if ways is None:
        return True
    return any(all(tooling.has(c) for c in way) for way in ways)


def substitute(joint: str, role: str, tooling: ShopTooling) -> str | None:
    """Best feasible joint for *role* when *joint* can't be made, else ``None``."""
    if can_make(joint, tooling):
        return None
    for candidate in ROLE_PREFERENCE.get(role, []):
        if candidate != _norm(joint) and can_make(candidate, tooling):
            return candidate
    return None


# --- walk a spec for the operations it requires ----------------------------

@dataclass
class Requirement:
    """One joint/boring operation a design calls for, and where."""
    role: str          # "carcass" | "drawer" | "frame" | "door" | "boring"
    joint: str         # a JOINT_WAYS key
    where: str         # human location, e.g. "Drawer 2 box corners"


def required_operations(spec) -> list[Requirement]:
    """Every joinery / boring operation *spec* needs, dispatched by spec kind.

    Recurses into a project/assembly so a whole run is covered. Pure spec
    inspection — mirrors what :func:`joinery.joinery_schedule` and
    :func:`drilling.drilling_schedule` actually emit.
    """
    from .dispatch import spec_kind, GROUP, TABLE, VOID

    kind = spec_kind(spec)
    if kind == VOID:
        return []
    if kind == GROUP:
        out: list[Requirement] = []
        for i, comp in enumerate(spec.components, start=1):
            tag = getattr(comp, "label", "") or f"#{i}"
            for r in required_operations(comp.spec):
                out.append(Requirement(r.role, r.joint, f"{tag}: {r.where}"))
        return out
    if kind == TABLE:
        return [Requirement("frame", _norm(getattr(spec, "joinery", "mortise_tenon")),
                            "leg-to-apron joints")]

    # A cabinet. ------------------------------------------------------------
    reqs: list[Requirement] = []
    reqs.append(Requirement("carcass", _norm(spec.joinery), "carcass case joints"))

    back = _norm(getattr(spec, "back", ""))
    if back == "rabbeted":
        reqs.append(Requirement("carcass", "rabbet", "rabbet for the back"))
    elif back == "grooved":
        reqs.append(Requirement("carcass", "groove", "groove for the back"))

    if getattr(spec, "construction", None) and \
            getattr(spec.construction, "value", spec.construction) == "face_frame":
        reqs.append(Requirement("frame", "pocket", "face-frame stile/rail joints"))

    style = _norm(getattr(spec, "door_style", "slab"))
    if getattr(spec, "doors", 0) and style not in ("slab", ""):
        reqs.append(Requirement("door", "cope_stick", "5-piece door frames"))

    if getattr(spec, "doors", 0):
        reqs.append(Requirement("boring", "hinge_cup", "concealed-hinge cups"))
    if getattr(spec, "shelves", 0):
        reqs.append(Requirement("boring", "shelf_pins", "adjustable-shelf pin rows"))

    for i, dr in enumerate(getattr(spec, "drawers", []) or [], start=1):
        if getattr(dr, "false_front", False):
            continue
        reqs.append(Requirement("drawer", _norm(dr.corner_joint),
                                f"Drawer {i} box corners"))
    return reqs


def tooling_advisories(spec, tooling: ShopTooling | None
                       ) -> list[tuple[str, str, str]]:
    """``(severity, field, message)`` for joints *tooling* can't make.

    One warning per infeasible operation, naming what it needs and — when the
    role has one — a feasible substitute you *could* make instead. Always
    advisory (``warning``): a tool gap is the builder's call, never a hard block
    on the math. Returns ``[]`` when *tooling* is ``None`` (unconstrained).
    """
    if tooling is None:
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    try:
        reqs = required_operations(spec)
    except Exception:
        return out
    for r in reqs:
        if can_make(r.joint, tooling):
            continue
        key = (r.joint, r.where)
        if key in seen:
            continue
        seen.add(key)
        need = requirement_text(r.joint)
        msg = (f"{r.where} use {JOINT_LABEL.get(r.joint, r.joint)}, which needs "
               f"{need} — not in your declared tooling")
        alt = substitute(r.joint, r.role, tooling)
        if alt:
            msg += f"; switch to {JOINT_LABEL.get(alt, alt)} (you can make that)"
        elif r.role == "boring":
            msg += "; have a shop with the bit bore these, or add the tool"
        out.append(("warning", "tooling", msg))
    return out


def feasible_joints(role: str, tooling: ShopTooling) -> list[str]:
    """The joints for *role* the shop can actually make, best first."""
    return [j for j in ROLE_PREFERENCE.get(role, []) if can_make(j, tooling)]


def designer_constraint(tooling: ShopTooling | None) -> str:
    """A prompt block telling the AI designer which joinery it may use.

    Empty string when *tooling* is ``None`` (no constraint). Lists the owned
    tools and the allowed joints per role so the model never specifies a joint
    the shop can't cut.
    """
    if tooling is None:
        return ""
    owned = ", ".join(CAP_LABEL.get(c, c) for c in tooling.owned()) or "hand tools only"
    carc = ", ".join(feasible_joints("carcass", tooling)) or "butt"
    draw = ", ".join(feasible_joints("drawer", tooling)) or "butt"
    frame = ", ".join(feasible_joints("frame", tooling)) or "screw"
    lines = [
        "\n== TOOLING CONSTRAINT ==",
        f"The shop owns ONLY: {owned}.",
        "Specify ONLY joinery this shop can make. Allowed values:",
        f'- cabinet "joinery" (and table "joinery", frames): {carc}',
        f'- drawer "corner_joint": {draw}',
        f"- face-frame / leg-to-apron joints: {frame}",
    ]
    if not can_make("cope_stick", tooling):
        lines.append('- no router table/router: use "door_style": "slab" '
                     "(no cope-and-stick 5-piece doors).")
    if not can_make("dovetail", tooling):
        lines.append('- no dovetail capability: do NOT use "corner_joint": '
                     '"dovetail".')
    lines.append("Pick the best ALLOWED joint for the job; never output a joint "
                 "not listed above.")
    return "\n".join(lines)


@dataclass
class ToolNeed:
    """A tool the design calls for, and whether the shop owns it."""
    operation: str        # human op label
    tool: str             # how it's made (requirement_text)
    where: str
    owned: bool | None    # True/False vs. None when no inventory was given


def tools_needed(spec, tooling: ShopTooling | None = None) -> list[ToolNeed]:
    """The tool/jig checklist a design requires.

    With a *tooling* inventory each line is marked owned/missing; without one,
    ``owned`` is ``None`` (just the list of what you'll need). Useful as a
    standalone "tool list" output even when nothing is constrained.
    """
    needs: list[ToolNeed] = []
    seen: set[str] = set()
    try:
        reqs = required_operations(spec)
    except Exception:
        return needs
    for r in reqs:
        if r.joint in seen:
            continue
        seen.add(r.joint)
        owned = None if tooling is None else can_make(r.joint, tooling)
        needs.append(ToolNeed(
            operation=JOINT_LABEL.get(r.joint, r.joint),
            tool=requirement_text(r.joint) or "—",
            where=r.where, owned=owned))
    return needs
