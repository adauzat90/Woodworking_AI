"""The furniture description language.

This module defines the *language* the AI agents write: a small, typed,
declarative spec that fully describes a piece of casework. A valid spec is the
single source of truth from which we derive geometry, a cut list, and a hardware
schedule.

The spec is plain dataclasses with JSON (de)serialization, so it has zero CAD
dependencies and can be produced, validated, diffed, and stored anywhere.

Units: the engine is **millimetre-native**. A spec may be authored in inches by
setting ``"units": "in"`` — :meth:`from_dict` converts every length to mm on
load and stamps ``units = "mm"``, so everything downstream is canonical mm.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum, StrEnum
from typing import Any
import copy
import json
import math

from .units import normalize_unit, IMPERIAL, MM_PER_IN


class CabinetType(StrEnum):
    BASE = "base"        # sits on the floor, toe kick, top stretchers
    WALL = "wall"        # hangs on the wall, no toe kick, full top
    TALL = "tall"        # floor-to-ceiling pantry/utility, toe kick, full top
    CORNER_BLIND = "corner_blind"        # door opening + a blind filler return
    CORNER_DIAGONAL = "corner_diagonal"  # 45° angled face with an angled door
    BOOKCASE = "bookcase"  # open shelving, enclosed top, no doors
    DRESSER = "dresser"    # a drawer bank / chest of drawers, enclosed top


class Construction(StrEnum):
    FRAMELESS = "frameless"      # Euro / frameless box
    FACE_FRAME = "face_frame"    # traditional face-frame


class BackStyle(StrEnum):
    RABBETED = "rabbeted"        # back sits in a rabbet on the sides/top/bottom
    APPLIED = "applied"          # back nailed/screwed to the rear edges
    GROOVED = "grooved"          # back captured in a groove


class Joinery(StrEnum):
    DADO = "dado"
    DOWEL = "dowel"
    DOMINO = "domino"
    SCREW = "screw"
    POCKET = "pocket"            # pocket-hole screws — fast, low racking
    BUTT = "butt"               # glued butt — weak in tension/shear
    RABBET = "rabbet"
    MORTISE_TENON = "mortise_tenon"  # strongest frame joint
    DOVETAIL = "dovetail"       # drawer corners, resists pull-apart
    BOX = "box"                 # finger joint, strong glue surface


class CornerJoint(StrEnum):
    """Drawer-box corner joint."""
    DOVETAIL = "dovetail"
    BOX = "box"
    RABBET = "rabbet"
    LOCKING_RABBET = "locking_rabbet"
    DOWEL = "dowel"
    BUTT = "butt"               # end-grain glue — weak, pulls apart


class DovetailTails(StrEnum):
    """Which member carries the tails of a drawer-front dovetail."""
    SIDES = "sides"             # correct: front can't be pulled off
    FRONT = "front"            # wrong: interlock doesn't resist opening


class SlideType(StrEnum):
    SIDE_MOUNT = "side_mount"
    UNDERMOUNT = "undermount"


class Grain(StrEnum):
    FLATSAWN = "flatsawn"
    QUARTERSAWN = "quartersawn"


class TopFixing(StrEnum):
    FLOATING = "floating"      # movement allowed (figure-8s, Z-clips, slots)
    FIXED = "fixed"           # rigid — cracks a solid top across the grain


def _coerce_enum(enum_cls: type[Enum], value: Any, *, aliases: dict | None = None):
    """Best-effort coerce *value* to *enum_cls*.

    Returns the matching enum member, or — when the value is unknown — the
    normalized lowercase string, so the validator can still flag it rather than
    the constructor raising on a typo. Already-correct members pass through.
    """
    if isinstance(value, enum_cls):
        return value
    s = str(value).strip().lower()
    if aliases and s in aliases:
        s = aliases[s]
    try:
        return enum_cls(s)
    except ValueError:
        return s


@dataclass
class Material:
    """Sheet-good thicknesses, in the spec's units (default mm)."""
    carcass: float = 18.0
    back: float = 6.0
    door: float = 18.0
    shelf: float = 18.0
    drawer_box: float = 12.0     # drawer box sides/front/back stock
    door_panel: float = 6.0      # centre panel of a 5-piece (stile-and-rail) door


@dataclass
class ToeKick:
    height: float = 100.0
    setback: float = 50.0


@dataclass
class Drawer:
    front_height: float = 140.0
    false_front: bool = False    # a fixed panel (e.g. sink tip-out), no box
    # --- box joinery + slide hardware (optional; defaults = good practice) ----
    corner_joint: CornerJoint = CornerJoint.DOVETAIL  # dovetail|box|rabbet|...
    dovetail_tails: DovetailTails = DovetailTails.SIDES  # tails on the sides so
                                     # the front can't pull off; "front" is wrong
    slide_type: SlideType = SlideType.SIDE_MOUNT     # side_mount | undermount
    slide_clearance: float = 12.7    # per-side gap for side-mount slides (½in)
    slide_length: float = 0.0        # nominal slide length; 0 = derive from depth

    def __post_init__(self) -> None:
        # Accept plain strings (e.g. from JSON) and normalize to the enums.
        self.corner_joint = _coerce_enum(CornerJoint, self.corner_joint)
        self.dovetail_tails = _coerce_enum(
            DovetailTails, self.dovetail_tails, aliases={"side": "sides"})
        self.slide_type = _coerce_enum(SlideType, self.slide_type)


def _to_mm(d: dict, fields: tuple[str, ...]) -> None:
    """Multiply the named length fields of *d* (in inches) by 25.4, in place."""
    for f in fields:
        v = d.get(f)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d[f] = v * MM_PER_IN


@dataclass
class CabinetSpec:
    """A parametric cabinet. All dimensions are *overall*, in `units`."""

    cabinet_type: CabinetType = CabinetType.BASE
    units: str = "mm"

    width: float = 600.0
    height: float = 720.0
    depth: float = 560.0

    material: Material = field(default_factory=Material)
    construction: Construction = Construction.FRAMELESS
    back: BackStyle = BackStyle.RABBETED
    joinery: Joinery = Joinery.DADO

    toe_kick: ToeKick | None = field(default_factory=ToeKick)
    shelves: int = 1
    doors: int = 2
    drawers: list[Drawer] = field(default_factory=list)

    reveal: float = 3.0          # gap around overlay doors/drawers
    door_style: str = "slab"     # slab | shaker | raised_panel | cope_stick
    panel_construction: str = "sheet"  # sheet | glue_up (solid-wood carcass)
    center_mullion: bool = False # vertical post/stile between a pair of doors
    blind_width: float = 0.0     # corner_blind: width of the blind/filler return
    corner_cut: float = 0.0      # corner_diagonal: leg length of the 45° chamfer
    edge_banding: bool = True
    name: str = "Cabinet"

    # --- engineering inputs (optional; sensible defaults keep old specs valid) -
    shelf_species: str = "plywood"   # drives shelf stiffness for the sag check
    shelf_load_kg_per_m: float = 25.0  # distributed shelf load; ~books/dishes
    anti_tip: bool = False           # wall restraint / anti-tip hardware provided

    # --- hardware (optional; drives the catalogue + drilling) ----------------
    hardware_brand: str = "generic"  # generic | blum | hettich | grass
    hinge_overlay: str = "overlay"   # overlay | half | inset

    # --- accessories: countertop, appliance cutout, filler, end panel, molding
    accessories: list = field(default_factory=list)

    @property
    def has_full_top(self) -> bool:
        """Enclosed-top units; base/corner cabinets use top rails instead."""
        return self.cabinet_type in (
            CabinetType.WALL, CabinetType.TALL,
            CabinetType.BOOKCASE, CabinetType.DRESSER)

    @property
    def is_corner(self) -> bool:
        return self.cabinet_type in (
            CabinetType.CORNER_BLIND, CabinetType.CORNER_DIAGONAL)

    # ---- derived dimensions (shared by builder/cutlist/estimator/critic) --

    @property
    def toe_kick_height(self) -> float:
        """Toe-kick height, or 0 when the cabinet has none."""
        return self.toe_kick.height if self.toe_kick else 0.0

    @property
    def box_height(self) -> float:
        """Carcass box height, i.e. overall height above the toe kick."""
        return self.height - self.toe_kick_height

    @property
    def interior_width(self) -> float:
        """Clear width between the two side panels."""
        return self.width - 2 * self.material.carcass

    @property
    def interior_depth(self) -> float:
        """Interior depth, with a captured back recessed by its thickness."""
        return self.depth - self.material.back

    # ---- serialization ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Enums -> their string values for clean JSON.
        d["cabinet_type"] = self.cabinet_type.value
        d["construction"] = self.construction.value
        d["back"] = self.back.value
        d["joinery"] = self.joinery.value
        for dr in d.get("drawers", []):
            for k in ("corner_joint", "dovetail_tails", "slide_type"):
                if isinstance(dr.get(k), Enum):
                    dr[k] = dr[k].value
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CabinetSpec":
        data = dict(data)  # don't mutate caller's dict
        # Imperial input -> canonical mm (lengths only; loads/counts unchanged).
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "height", "depth", "reveal",
                          "blind_width", "corner_cut"))
            if isinstance(data.get("material"), dict):
                _to_mm(data["material"],
                       ("carcass", "back", "door", "shelf", "drawer_box"))
            if isinstance(data.get("toe_kick"), dict):
                _to_mm(data["toe_kick"], ("height", "setback"))
            for dr in (data.get("drawers") or []):
                if isinstance(dr, dict):
                    _to_mm(dr, ("front_height", "slide_clearance", "slide_length"))
            data["units"] = "mm"

        if "material" in data and isinstance(data["material"], dict):
            data["material"] = Material(**data["material"])
        if data.get("toe_kick") is not None and isinstance(data["toe_kick"], dict):
            data["toe_kick"] = ToeKick(**data["toe_kick"])
        if "drawers" in data and data["drawers"]:
            data["drawers"] = [
                Drawer(**d) if isinstance(d, dict) else d for d in data["drawers"]
            ]
        # Accept a legacy/loose "type" string (e.g. "wall_cabinet") and map it.
        if "cabinet_type" not in data and "type" in data:
            t = str(data["type"]).lower()
            if "wall" in t:
                data["cabinet_type"] = CabinetType.WALL
            elif "tall" in t or "pantry" in t:
                data["cabinet_type"] = CabinetType.TALL
            else:
                data["cabinet_type"] = CabinetType.BASE
        for key, enum_cls in (
            ("cabinet_type", CabinetType),
            ("construction", Construction),
            ("back", BackStyle),
            ("joinery", Joinery),
        ):
            # Structural enums are strict: an unknown value raises rather than
            # silently degrading, because it picks the whole build path.
            if key in data and not isinstance(data[key], enum_cls):
                data[key] = enum_cls(data[key])
        # Ignore unknown keys so the language can evolve without breaking old specs.
        known = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "CabinetSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class TableSpec:
    """A parametric table: a top on four legs joined by aprons.

    Coordinates match the cabinet frame: X = length, Y = depth, Z = height.
    """

    kind: str = "table"
    units: str = "mm"
    name: str = "Table"
    width: float = 1200.0        # length of the top (X)
    depth: float = 750.0         # width of the top (Y)
    height: float = 740.0        # floor to top surface (Z)
    top_thickness: float = 25.0
    leg: float = 60.0            # square leg cross-section
    apron_height: float = 90.0
    apron_thickness: float = 20.0
    leg_inset: float = 40.0      # leg outer face set in from the top edge

    # --- material/movement (optional; defaults describe a well-built top) ------
    solid_top: bool = True       # solid wood (moves) vs. a stable sheet good
    top_fixing: TopFixing = TopFixing.FLOATING  # movement allowed vs. rigid
    grain: Grain = Grain.FLATSAWN               # affects seasonal movement
    joinery: Joinery = Joinery.MORTISE_TENON    # leg-to-apron; drives racking

    def __post_init__(self) -> None:
        self.top_fixing = _coerce_enum(TopFixing, self.top_fixing)
        self.grain = _coerce_enum(
            Grain, self.grain, aliases={"quarter": "quartersawn",
                                        "quarter_sawn": "quartersawn",
                                        "flat": "flatsawn", "flat_sawn": "flatsawn"})
        self.joinery = _coerce_enum(Joinery, self.joinery)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("top_fixing", "grain", "joinery"):
            if isinstance(getattr(self, k), Enum):
                d[k] = getattr(self, k).value
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "top_thickness", "leg",
                          "apron_height", "apron_thickness", "leg_inset"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "TableSpec":
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Assemblies. A component group places child specs in one frame:
#   * Project  — the top-level run / built-in (e.g. a whole kitchen).
#   * Assembly — a *named, reusable sub-assembly*: a group that nests inside a
#     component and moves as one unit (a drawer bank, a wall-cabinet pair, ...).
# Both share :class:`ComponentGroup`, so every pipeline stage (validate, cut
# list, estimate, drilling, geometry) handles them identically and recurses
# into each component's spec — nesting "just works".
#
# Reuse (define-once, place-many) is expressed with ``definitions`` + ``ref``:
# a group declares named sub-assemblies under ``definitions`` and a component
# places a fresh copy of one by setting ``ref`` instead of an inline ``spec``.
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """One placed piece of furniture within a :class:`ComponentGroup`.

    ``x``/``y`` locate the component's origin in the parent frame (mm);
    ``rotation`` is degrees CCW about the vertical axis (for corner returns and
    sub-assembly orientation). The spec may be a leaf (cabinet/table) or a nested
    :class:`Assembly`. ``ref`` names a sub-assembly in the enclosing group's
    ``definitions``; on load it is resolved to a fresh copy placed here, so one
    definition can be dropped in many times. Placement drives the assembly view
    and an overlap sanity check — the per-component cut list is unaffected by
    where the piece sits.
    """
    spec: "CabinetSpec | TableSpec | Assembly | Project | None" = None
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    label: str = ""
    ref: str = ""                 # name of a definition this component instances


class _Defs:
    """A chained registry of named sub-assembly definitions.

    Definitions are resolved lazily (so one may reference another) with a visit
    stack that turns a cyclic reference into a clear error rather than infinite
    recursion. ``parent`` lets a nested group see the definitions declared by an
    enclosing group, with the innermost declaration winning.
    """

    def __init__(self, raw: dict | None, parent: "_Defs | None" = None) -> None:
        self.raw = dict(raw or {})
        self.parent = parent
        self.parsed: dict[str, Any] = {}

    def resolve(self, name: str, stack: frozenset) -> Any:
        if name in self.parsed:
            return self.parsed[name]
        if name in self.raw:
            if name in stack:
                raise ValueError(f"cyclic sub-assembly reference: {name!r}")
            spec = _spec_from_dict(self.raw[name], self, stack | {name})
            self.parsed[name] = spec
            return spec
        if self.parent is not None:
            return self.parent.resolve(name, stack)
        raise ValueError(f"unknown sub-assembly ref: {name!r}")

    def local(self, stack: frozenset) -> dict[str, Any]:
        """All definitions declared at this level, parsed (for round-tripping)."""
        return {name: self.resolve(name, stack) for name in self.raw}


def _component_from_dict(c: dict, defs: "_Defs", stack: frozenset) -> Component:
    ref = str(c.get("ref", "") or "")
    if ref:
        # A reference instances a *fresh copy* so edits to one placement don't
        # bleed into its siblings (and so each can sit at its own coordinates).
        spec = copy.deepcopy(defs.resolve(ref, stack))
    else:
        spec = _spec_from_dict(c.get("spec", c), defs, stack)
    return Component(
        spec=spec, ref=ref,
        x=float(c.get("x", 0.0)), y=float(c.get("y", 0.0)),
        rotation=float(c.get("rotation", 0.0)),
        label=str(c.get("label", "")),
    )


@dataclass
class ComponentGroup:
    """A named group of placed components that assemble and move as one unit.

    Base for :class:`Project` (top-level run) and :class:`Assembly` (a nestable,
    reusable sub-assembly). The whole pipeline dispatches on this type and
    aggregates across ``components``, recursing into each component's spec, so a
    group of groups is handled with no special cases.
    """
    name: str = "Group"
    units: str = "mm"
    components: list[Component] = field(default_factory=list)
    # Named reusable sub-assemblies a component can place by ``ref``.
    definitions: dict[str, Any] = field(default_factory=dict)
    kind: str = "group"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "name": self.name, "units": "mm"}
        if self.definitions:
            d["definitions"] = {n: s.to_dict() for n, s in self.definitions.items()}
        comps: list[dict[str, Any]] = []
        for c in self.components:
            item: dict[str, Any] = {
                "label": c.label, "x": c.x, "y": c.y, "rotation": c.rotation}
            if c.ref:
                item["ref"] = c.ref          # placements stay terse; spec lives
            else:                            # once, in `definitions`
                item["spec"] = c.spec.to_dict()
            comps.append(item)
        d["components"] = comps
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *,
                  parent_defs: "_Defs | None" = None,
                  _stack: frozenset = frozenset()) -> "ComponentGroup":
        data = dict(data)
        defs = _Defs(data.get("definitions"), parent=parent_defs)
        comps = [
            _component_from_dict(c, defs, _stack)
            for c in data.get("components", []) if isinstance(c, dict)
        ]
        return cls(
            name=str(data.get("name", cls().name)),
            units="mm", components=comps,
            definitions=defs.local(_stack),
        )

    @classmethod
    def from_json(cls, text: str) -> "ComponentGroup":
        return cls.from_dict(json.loads(text))


@dataclass
class Project(ComponentGroup):
    """A collection of placed components — a multi-cabinet run / built-in.

    The whole pipeline (validate, cut list, estimate) accepts a Project and
    aggregates across its components, so a kitchen yields one combined cut list
    and one quote. Components may be leaf cabinets/tables or nested
    :class:`Assembly` sub-assemblies.
    """
    name: str = "Project"
    kind: str = "project"


@dataclass
class Assembly(ComponentGroup):
    """A named, reusable sub-assembly: a group of components placed and moved as
    one unit, that nests inside a component of another group.

    Use it both inline (a component whose ``spec`` is an Assembly) and as a
    reusable definition (declared under a group's ``definitions`` and dropped in
    by ``ref``). Its own components are positioned in the assembly's *local*
    frame, anchored at the assembly origin; placing the assembly translates and
    rotates that whole frame.
    """
    name: str = "Assembly"
    kind: str = "assembly"


def place_run(specs, *, start: tuple[float, float] = (0.0, 0.0),
              angle: float = 0.0, gap: float = 0.0,
              labels: list[str] | None = None) -> list[Component]:
    """Lay specs end-to-end along a wall, returning placed :class:`Component`s.

    ``start`` is the front-left corner of the first piece; ``angle`` is the wall
    direction in degrees (0 = +X, 90 = +Y), so an L-/U-shaped kitchen is just a
    few runs at right angles:

        run_a = place_run([a, b, c], start=(0, 0),    angle=0)
        run_b = place_run([d, e],    start=(2400, 0), angle=90)
        kitchen = Project(components=run_a + run_b)

    Each piece is offset along the wall by the previous piece's width (+ ``gap``)
    and rotated to face out of the wall, so the footprints abut without
    overlapping. Leave a gap (or drop in a corner unit) where two runs meet.
    """
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out: list[Component] = []
    cursor = 0.0
    for i, spec in enumerate(specs):
        w = float(getattr(spec, "width", 0.0) or 0.0)
        out.append(Component(
            spec=spec, x=start[0] + ux * cursor, y=start[1] + uy * cursor,
            rotation=angle,
            label=(labels[i] if labels and i < len(labels) else "")))
        cursor += w + gap
    return out


def _spec_from_dict(data: dict[str, Any], defs: "_Defs | None", stack: frozenset):
    """Pick the right spec, threading the definition registry into groups."""
    kind = str(data.get("kind", "")).lower()
    if kind == "assembly":
        return Assembly.from_dict(data, parent_defs=defs, _stack=stack)
    if kind == "project" or "components" in data:
        return Project.from_dict(data, parent_defs=defs, _stack=stack)
    if kind == "table" or "leg" in data or "top_thickness" in data:
        return TableSpec.from_dict(data)
    return CabinetSpec.from_dict(data)


def spec_from_dict(data: dict[str, Any]):
    """Pick the right furniture spec from a payload.

    Routes to a cabinet, table, :class:`Project` run, or :class:`Assembly`
    sub-assembly. Component ``ref``s are resolved against the group's
    ``definitions`` (define-once, place-many); a cyclic or unknown reference
    raises ``ValueError``.
    """
    return _spec_from_dict(data, None, frozenset())


# ---------------------------------------------------------------------------
# Schema description handed to the LLM designer. The enum value lists are
# generated from the dataclasses above so the prompt can never advertise a
# vocabulary that drifts from the code (guarded by tests/test_schema_hint.py).
# ---------------------------------------------------------------------------

def _opts(enum_cls: type[Enum]) -> str:
    return " | ".join(f'"{m.value}"' for m in enum_cls)


DSL_SCHEMA_HINT = f"""\
Output ONE furniture spec as a JSON object. It is either a CABINET or a TABLE.
Set "units" to "mm" (default) or "in"; give every dimension in that unit and do
not mix — inches are converted to millimetres on load.

== CABINET ==
{{
  "cabinet_type": {_opts(CabinetType)},
  "name": "Sink Base",
  "units": "mm",
  "width": <overall width>,
  "height": <overall height, including toe kick>,
  "depth": <overall depth>,
  "material": {{"carcass": 18, "back": 6, "door": 18, "shelf": 18,
               "drawer_box": 12, "door_panel": 6}},
  "construction": {_opts(Construction)},
  "door_style": "slab" | "shaker" | "raised_panel" | "cope_stick",
  "panel_construction": "sheet" | "glue_up",   // glue_up = solid-wood carcass
  "back": {_opts(BackStyle)},
  "joinery": {_opts(Joinery)},
  "toe_kick": {{"height": 100, "setback": 50}}  | null,
  "shelves": <integer count of adjustable shelves>,
  "doors": <integer count of doors, 0, 1 or 2>,
  "drawers": [{{"front_height": 140, "false_front": false,
               "corner_joint": {_opts(CornerJoint)},
               "dovetail_tails": {_opts(DovetailTails)},
               "slide_type": {_opts(SlideType)},
               "slide_clearance": 12.7}}, ...],
  "reveal": <gap in mm around overlay doors/drawers, e.g. 3>,
  "center_mullion": <true to add a vertical post between a pair of doors>,
  "blind_width": <corner_blind only: width of the blind/filler return>,
  "corner_cut": <corner_diagonal only: leg length of the 45 degree chamfer>,
  "edge_banding": true | false,
  "shelf_species": "plywood" | "mdf" | "particleboard" | "oak" | "maple" | ...,
  "shelf_load_kg_per_m": <expected shelf load, e.g. 25 (books ~20-40)>,
  "anti_tip": true | false,
  "hardware_brand": "generic" | "blum" | "hettich" | "grass",
  "hinge_overlay": "overlay" | "half" | "inset",
  "accessories": [        // optional countertop / appliance / filler / molding
    {{"kind": "countertop", "depth": 640, "thickness": 38,
      "material": "butcher_block", "overhang": 25}},
    {{"kind": "appliance", "type": "sink", "cutout_w": 700, "cutout_d": 450}},
    {{"kind": "filler", "width": 75, "side": "left"}},
    {{"kind": "end_panel", "side": "right"}},
    {{"kind": "molding", "type": "crown", "height": 90}}
  ]
}}

== TABLE ==
{{
  "kind": "table",
  "name": "Dining Table",
  "units": "mm",
  "width": <length of the top>,
  "depth": <width of the top>,
  "height": <floor to top surface, ~740>,
  "top_thickness": 25,
  "leg": <square leg cross-section, e.g. 60>,
  "apron_height": 90,
  "apron_thickness": 20,
  "leg_inset": <leg outer face set in from the top edge, e.g. 40>,
  "solid_top": true | false,
  "top_fixing": {_opts(TopFixing)},
  "grain": {_opts(Grain)},
  "joinery": {_opts(Joinery)}
}}

== PROJECT / ASSEMBLY (multi-part) ==
For anything with more than one piece — a kitchen run, a built-in, a wall of
cabinets — emit a PROJECT: a list of placed components. Each component sits at
an (x, y) origin in millimetres (front-left corner for a cabinet) and an optional
"rotation" in degrees CCW about vertical (use 90 to turn a run around a corner).
{{
  "kind": "project",
  "name": "Kitchen",
  "units": "mm",
  "definitions": {{                 // optional: named, reusable SUB-ASSEMBLIES
    "drawer_bank": {{
      "kind": "assembly",
      "name": "Drawer Bank",
      "components": [
        {{"spec": {{ <a cabinet or table spec> }}, "x": 0, "y": 0}},
        {{"spec": {{ ... }}, "x": 600, "y": 0}}
      ]
    }}
  }},
  "components": [
    {{"spec": {{ <a cabinet/table/assembly spec> }}, "x": 0, "y": 0, "label": "B1"}},
    {{"ref": "drawer_bank", "x": 1200, "y": 0, "label": "B2"}}  // place a copy of
  ]                                                             // a definition
}}
An ASSEMBLY ("kind": "assembly") is the same shape as a project but is meant to
nest: use it for a repeated group (a drawer bank, a wall-cabinet pair) so it
moves as one unit. Place a sub-assembly either inline (a component whose "spec"
is the assembly) or by reference — declare it once under "definitions" and drop
it in many times with "ref": "<name>" (each ref is an independent copy, so give
each its own x/y). Assemblies may nest, but a reference must not form a cycle.
Lay pieces edge-to-edge by stepping x by the previous piece's width; do not let
footprints overlap (the validator checks plan collisions across the whole run,
including sub-assemblies).

The validator checks shelf sag (deflection vs span/360) from shelf_species,
shelf thickness, span and load — prefer thicker/stiffer shelves or shorter
spans for heavy loads. Tall units and dressers >=686mm should set anti_tip
true (ASTM F2057 tip-over). Toe kicks should be >=75mm high and >=50mm deep.
Drawer corners should be "dovetail", "box", or "rabbet" (a "butt" corner is
weak); side-mount slides need ~12.7mm clearance per side. Sheet thicknesses
should be real stock (6/9/12/15/18/21/25mm) and panels should fit a
2440×1220mm sheet. Doors take 35mm concealed hinges, so door stock should be
≥16mm thick and each door wide enough (>50mm) to host the cup. Dovetailed
drawers keep their tails on the sides so the front can't pull off. Cabinets
with adjustable shelves need a box tall and deep enough for the 32mm drilling
system. A solid table top must use a "floating" top_fixing so it can move
seasonally; mortise_tenon or domino leg-to-apron joints resist racking best.

Rules of thumb by cabinet_type:
- base: floor cabinet, ~720mm box + ~100mm toe kick, 560-600mm deep. Has a toe
  kick; the top is open (rails), so a counter can sit on it.
- wall: hangs on the wall, NO toe kick (set "toe_kick": null), 300-400mm deep,
  600-900mm tall, enclosed top. Usually doors only, no drawers.
- tall: pantry/utility, floor to near ceiling (1900-2400mm), has a toe kick,
  enclosed top, many shelves.
- corner_blind: a base cabinet with one open door bay; set "blind_width" to the
  filler return that tucks behind the adjacent run (leave a usable opening).
- corner_diagonal: an angled-front corner cabinet; set "corner_cut" to the 45
  degree chamfer leg (smaller than width and depth).
- bookcase: open shelving, enclosed top, "doors": 0 and several "shelves".
- dresser: a drawer bank / chest, enclosed top; populate "drawers".
Convert any imperial dimensions to mm (1 in = 25.4 mm) or set "units": "in".
"""
