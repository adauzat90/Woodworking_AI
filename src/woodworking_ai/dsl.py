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
from .constants import SLIDE_SIDE_CLEARANCE


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


class ShelfFixing(StrEnum):
    """How a wall shelf attaches to the wall."""
    FRENCH_CLEAT = "french_cleat"   # a 45deg-bevel cleat pair (wall + shelf)
    BRACKETS = "brackets"           # a pair (or more) of L-brackets
    HIDDEN = "hidden"               # concealed rod/blind-shelf hardware


class FrameJoint(StrEnum):
    """How the four rails of a picture/mirror frame meet at the corners."""
    MITER = "miter"                 # plain 45° glued miter — end grain, weak
    SPLINED_MITER = "splined_miter"  # miter + a corner spline/key — strong
    COPE_STICK = "cope_stick"       # cope-and-stick rail-and-stile profile
    HALF_LAP = "half_lap"           # overlapping half-laps — strong, shows grain


class FrameHanger(StrEnum):
    """How a finished frame hangs on the wall."""
    SAWTOOTH = "sawtooth"           # a single sawtooth hanger (light art)
    D_RING_WIRE = "d_ring_wire"     # two D-rings + a wire (most pictures)
    CLEAT = "cleat"                 # a French cleat (heavy frames / mirrors)


class FrameContents(StrEnum):
    """What the frame holds — drives glazing and hanging-load advice."""
    ART = "art"                     # photo / print / canvas behind glazing
    MIRROR = "mirror"               # a mirror (heavy; no separate glazing)
    NONE = "none"                   # an empty / open frame


class BedSize(StrEnum):
    """Standard mattress sizes; map to a mattress W×L in :data:`MATTRESS_SIZES`."""
    TWIN = "twin"
    TWIN_XL = "twin_xl"
    FULL = "full"
    QUEEN = "queen"
    KING = "king"
    CAL_KING = "cal_king"
    CUSTOM = "custom"               # use explicit mattress_w / mattress_l


# Nominal mattress sizes (mm), converted from the US inch standards. A real
# mattress runs a little under these, so the rails add a clearance gap.
MATTRESS_SIZES = {
    BedSize.TWIN:    (38 * MM_PER_IN, 75 * MM_PER_IN),
    BedSize.TWIN_XL: (38 * MM_PER_IN, 80 * MM_PER_IN),
    BedSize.FULL:    (54 * MM_PER_IN, 75 * MM_PER_IN),
    BedSize.QUEEN:   (60 * MM_PER_IN, 80 * MM_PER_IN),
    BedSize.KING:    (76 * MM_PER_IN, 80 * MM_PER_IN),
    BedSize.CAL_KING: (72 * MM_PER_IN, 84 * MM_PER_IN),
}


class BedConnector(StrEnum):
    """Knock-down hardware joining the side rails to the head/foot posts."""
    BED_BOLT = "bed_bolt"           # a through-bolt into a cross-dowel nut
    HOOK_PLATE = "hook_plate"       # interlocking bed-rail hook brackets


class GrainStyle(StrEnum):
    """Glue-up grain orientation for a cutting / charcuterie board."""
    EDGE_GRAIN = "edge_grain"       # strips on edge — the everyday board
    END_GRAIN = "end_grain"         # end grain up — a butcher block, knife-kind
    LONG_GRAIN = "long_grain"       # face grain — a serving/charcuterie board


class ApplianceType(StrEnum):
    SINK = "sink"             # drop-in/undermount, hosted by a countertop cutout
    COOKTOP = "cooktop"       # surface unit, also a countertop cutout
    RANGE = "range"           # slide-in/freestanding stove — occupies a GAP
    WALL_OVEN = "wall_oven"   # built into a tall cabinet opening
    DISHWASHER = "dishwasher" # occupies a GAP under the counter, not a box
    FRIDGE = "fridge"         # freestanding/built-in, occupies a GAP
    MICROWAVE = "microwave"   # built-in / over-the-range
    HOOD = "hood"             # range hood / extractor


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


# Physical material forms a shop can actually buy. Sheet goods are sold by the
# sheet; "solid" is dimensional / hardwood lumber sold by the board foot. Both a
# part's form and its species are *optional* — see :class:`Stock`.
SHEET_FORMS = ("plywood", "mdf", "particleboard", "melamine", "hardboard")
SOLID_FORMS = ("solid",)
MATERIAL_FORMS = SHEET_FORMS + SOLID_FORMS


@dataclass
class Stock:
    """An optional material choice for one *area* of a piece.

    ``form`` is the physical material (``plywood`` | ``mdf`` | ``particleboard``
    | ``melamine`` | ``hardboard`` | ``solid``); ``species`` is the wood (``oak``,
    ``maple``, ``pine``, ...). Both are optional — an empty value inherits the
    spec's global default (``material_form`` / ``species``), and when nothing is
    declared anywhere the area is treated as a generic sheet good. Used to drive
    the shopping list grouping, the cost estimate, and material build hints.
    """
    form: str = ""
    species: str = ""

    def __post_init__(self) -> None:
        self.form = str(self.form or "").strip().lower()
        self.species = str(self.species or "").strip()

    def to_dict(self) -> dict[str, str]:
        d: dict[str, str] = {}
        if self.form:
            d["form"] = self.form
        if self.species:
            d["species"] = self.species
        return d


def _stock_map(raw: Any) -> dict[str, "Stock"]:
    """Parse a ``{area: {form, species}}`` mapping into :class:`Stock` values.

    Accepts a Stock, a dict, or a bare string (treated as the species), so the
    language stays forgiving for hand-written specs. Empty entries are dropped.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Stock] = {}
    for area, v in raw.items():
        if isinstance(v, Stock):
            s = v
        elif isinstance(v, dict):
            s = Stock(form=str(v.get("form", "") or ""),
                      species=str(v.get("species", "") or ""))
        elif isinstance(v, str):
            s = Stock(species=v)          # shorthand: "oak" == {"species": "oak"}
        else:
            continue
        if s.form or s.species:
            out[str(area).strip().lower()] = s
    return out


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
    slide_clearance: float = SLIDE_SIDE_CLEARANCE    # per-side gap, side-mount
    slide_length: float = 0.0        # nominal slide length; 0 = derive from depth

    def __post_init__(self) -> None:
        # Accept plain strings (e.g. from JSON) and normalize to the enums.
        self.corner_joint = _coerce_enum(CornerJoint, self.corner_joint)
        self.dovetail_tails = _coerce_enum(
            DovetailTails, self.dovetail_tails, aliases={"side": "sides"})
        self.slide_type = _coerce_enum(SlideType, self.slide_type)


@dataclass
class Appliance:
    """A typed kitchen appliance hosted by a cabinet/run.

    A first-class form of the loose ``{"kind": "appliance", ...}`` accessory
    dict. ``cutout_w``/``cutout_d`` size the opening it needs (a sink/cooktop
    cutout in a countertop; a gap width for a range/dishwasher/fridge);
    ``width``/``height``/``depth`` are the appliance's own envelope. Adds no
    cut-list part — it's a hole/void the validator sanity-checks. ``panel_ready``
    marks an appliance (e.g. a dishwasher) that takes a custom finish panel.
    """
    type: ApplianceType = ApplianceType.SINK
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    cutout_w: float = 0.0
    cutout_d: float = 0.0
    panel_ready: bool = False

    def __post_init__(self) -> None:
        self.type = _coerce_enum(ApplianceType, self.type)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = "appliance"      # round-trips into the accessories list
        d["type"] = self.type.value if isinstance(self.type, Enum) else self.type
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Appliance":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# Nominal cabinetry gap(s) an appliance needs, by type (mm). A run reserves this
# as an :class:`ApplianceVoid`; the validator warns when a void is mis-sized. A
# type may list several standard widths (e.g. a 760mm slide-in or a 900mm pro
# range); the closest one is used for the fit check.
APPLIANCE_VOID_WIDTHS: dict[str, tuple[float, ...]] = {
    "dishwasher": (600.0,),
    "range": (760.0, 900.0),   # standard slide-in / freestanding, or a pro range
    "fridge": (915.0,),        # 36in standard-depth refrigerator opening
}
# How far a void width may stray from the nearest nominal before it's flagged.
APPLIANCE_VOID_TOLERANCE = 25.0


@dataclass
class ApplianceVoid:
    """A reserved GAP in a run for a free-standing appliance — a SPACE, not a box.

    A dishwasher, range, or fridge is slotted into an opening between cabinets; it
    needs run width and floor footprint but no carcass is built for it. Placed as
    a component's ``spec`` inside a :class:`Project`, it occupies its width on the
    wall and its footprint in plan (so the overlap check treats it as filled), and
    drives finished end panels on the cabinets either side. It adds **no** part to
    the cut list and **no** holes to drill.
    """
    type: ApplianceType = ApplianceType.DISHWASHER
    width: float = 600.0
    depth: float = 600.0
    name: str = "Appliance gap"
    kind: str = "appliance_void"   # tags the component spec on (de)serialisation

    def __post_init__(self) -> None:
        self.type = _coerce_enum(ApplianceType, self.type)

    @property
    def nominal_widths(self) -> tuple[float, ...]:
        """The standard opening width(s) for this appliance type (mm); () if any."""
        t = self.type.value if isinstance(self.type, Enum) else str(self.type)
        return APPLIANCE_VOID_WIDTHS.get(t.lower(), ())

    @property
    def nominal_width(self) -> float | None:
        """The standard opening width closest to this gap's width (mm), if known."""
        widths = self.nominal_widths
        if not widths:
            return None
        return min(widths, key=lambda n: abs(n - self.width))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "appliance_void",
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "width": self.width, "depth": self.depth, "name": self.name,
            "schema_version": SCHEMA_VERSION,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApplianceVoid":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def appliances_of(spec) -> list[Appliance]:
    """Yield the typed :class:`Appliance` objects on *spec*'s accessories.

    Bridges the loose list-of-dicts ``accessories`` form to typed appliances:
    each ``{"kind": "appliance", ...}`` dict (or an already-:class:`Appliance`)
    is normalized to an :class:`Appliance`. Other accessory kinds are skipped.
    """
    out: list[Appliance] = []
    for a in getattr(spec, "accessories", None) or []:
        if isinstance(a, Appliance):
            out.append(a)
        elif isinstance(a, dict) and str(a.get("kind", "")).lower() == "appliance":
            out.append(Appliance.from_dict(a))
    return out


# ---------------------------------------------------------------------------
# Typed accessories. The accessory list is stored as plain ``{"kind": ...}``
# dicts (so the six consumers — cut list, geometry, estimate, render, validator,
# diffing — read one shape). These dataclasses are an *authoring convenience*:
# build a piece with ``Countertop(...)`` instead of a raw dict, and
# :meth:`CabinetSpec.__post_init__` normalizes it straight back to the canonical
# dict on construction, so storage and every consumer are unchanged.
# ---------------------------------------------------------------------------

# Allowed enum-ish accessory values (validated; not strict-coerced so a loose
# spec still loads and the validator flags it).
ACCESSORY_SIDES = ("left", "right")
MOLDING_TYPES = ("crown", "cove", "base", "light_rail", "scribe")
COUNTERTOP_MATERIALS = (
    "laminate", "butcher_block", "solid_surface", "quartz", "granite", "stone")


@dataclass
class Countertop:
    """A countertop slab over a cabinet/run; may host a sink/cooktop cutout."""
    depth: float = 0.0           # 0 -> derive from the cabinet depth on use
    thickness: float = 38.0
    material: str = "laminate"
    overhang: float = 25.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": "countertop", "thickness": self.thickness,
                             "material": self.material, "overhang": self.overhang}
        if self.depth:
            d["depth"] = self.depth
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Countertop":
        return cls(depth=float(data.get("depth", 0.0) or 0.0),
                   thickness=float(data.get("thickness", 38.0) or 38.0),
                   material=str(data.get("material", "laminate") or "laminate"),
                   overhang=float(data.get("overhang", 25.0) or 25.0))


@dataclass
class Filler:
    """A scribe filler that closes the gap from a cabinet/run to the wall."""
    width: float = 75.0
    side: str = ""               # "" | left | right

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": "filler", "width": self.width}
        if self.side:
            d["side"] = self.side
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Filler":
        return cls(width=float(data.get("width", 75.0) or 75.0),
                   side=str(data.get("side", "") or "").strip().lower())


@dataclass
class EndPanel:
    """A finished panel applied to an exposed cabinet end."""
    side: str = ""               # "" | left | right

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": "end_panel"}
        if self.side:
            d["side"] = self.side
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EndPanel":
        return cls(side=str(data.get("side", "") or "").strip().lower())


@dataclass
class Molding:
    """Crown / light-rail / scribe molding run along the top or bottom."""
    type: str = "crown"
    height: float = 0.0          # 0 -> derived per type on use
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": "molding", "type": self.type}
        if self.height:
            d["height"] = self.height
        if self.profile:
            d["profile"] = self.profile
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Molding":
        return cls(type=str(data.get("type", "crown") or "crown").strip().lower(),
                   height=float(data.get("height", 0.0) or 0.0),
                   profile=str(data.get("profile", "") or "").strip().lower())


def _accessory_to_dict(a: Any) -> Any:
    """Normalize one accessory to its canonical dict (typed -> dict; dict as-is)."""
    if hasattr(a, "to_dict") and not isinstance(a, dict):
        return a.to_dict()
    return a


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

    # --- finishing (optional; drives the finish schedule + cost) -------------
    finish: str = "none"         # none | oil | clear | paint | stain_clear
    finish_sheen: str = "satin"  # matte | satin | semi_gloss | gloss

    # --- material make-up (all optional; feed the BOM, cost, and build hints) -
    # Global defaults for the whole piece; override any area through `stock`.
    # Leave empty and the piece is treated as a single generic sheet good.
    material_form: str = ""      # plywood|mdf|particleboard|melamine|hardboard|solid
    species: str = ""            # wood species, e.g. oak | maple | pine (free text)
    # Per-area overrides keyed by area: carcass | back | shelf | front (doors &
    # drawer fronts) | door_panel | drawer_box | frame (face frame) | accessory.
    stock: dict[str, Stock] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Typed accessories (Countertop/Filler/...) are an authoring convenience;
        # store them as the canonical dicts every consumer reads.
        if self.accessories:
            self.accessories = [_accessory_to_dict(a) for a in self.accessories]

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
        # Material overrides round-trip as a terse {area: {form, species}} map.
        if self.stock:
            d["stock"] = {a: s.to_dict() for a, s in self.stock.items()}
        else:
            d.pop("stock", None)
        d["schema_version"] = SCHEMA_VERSION
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
        if "stock" in data and not isinstance(data["stock"], dict):
            data.pop("stock")
        elif "stock" in data:
            data["stock"] = _stock_map(data["stock"])
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
    finish: str = "none"         # none | oil | clear | paint | stain_clear
    finish_sheen: str = "satin"

    # --- material make-up (optional; feed the BOM, cost, and build hints) -----
    material_form: str = ""      # usually "solid"; "" treats the top as a sheet
    species: str = ""            # wood species, e.g. oak | maple | walnut

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
        d["schema_version"] = SCHEMA_VERSION
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


@dataclass
class WallShelfSpec:
    """A wall-mounted shelf: one board fixed to the wall by a cleat or brackets.

    The simplest leaf furniture — a board plus its fixing — so it is the proving
    ground for the H0 leaf-furniture path. Coordinates match the shared frame:
    X = length, Y = depth (front to wall), Z = height (the mounting height).
    """

    kind: str = "wall_shelf"
    units: str = "mm"
    name: str = "Wall shelf"
    length: float = 800.0        # along the wall (X)
    depth: float = 200.0         # out from the wall (Y)
    thickness: float = 25.0      # board thickness (Z)
    mount_height: float = 1400.0  # where the shelf top hangs off the floor (install)
    fixing: ShelfFixing = ShelfFixing.FRENCH_CLEAT
    brackets: int = 2            # bracket count (fixing="brackets")

    # --- engineering inputs (optional; drive the deflection check) ------------
    load_kg_per_m: float = 15.0  # distributed load along the shelf (books ~20-40)

    # --- finishing / material (optional; feed the BOM, cost, build hints) -----
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = "solid"   # a shelf board is usually solid stock
    species: str = ""              # wood species, e.g. oak | pine | walnut

    def __post_init__(self) -> None:
        self.fixing = _coerce_enum(ShelfFixing, self.fixing)

    @property
    def width(self) -> float:
        """Alias for the placement layer: a shelf's plan width is its length.

        The project frame anchors a leaf by its front-left corner over ``width``
        (X) × ``depth`` (Y); a shelf is centred on X over its ``length`` with its
        front at Y=0 — the same convention — so exposing ``width`` lets a shelf
        place and overlap-check inside a Project with no special case.
        """
        return self.length

    @property
    def cleat_height(self) -> float:
        """Height (Z) of each French-cleat strip — a fraction of the depth."""
        return min(max(self.depth * 0.4, 40.0), 100.0)

    @property
    def bracket_height(self) -> float:
        """Height (Z) of a wall bracket below the board."""
        return min(max(self.depth * 0.6, 60.0), max(self.mount_height, 60.0))

    @property
    def height(self) -> float:
        """The built artifact's own Z-extent (board + the fixing that hangs below).

        Distinct from ``mount_height`` (where it sits on the wall). Equals the
        Z-span of the panels, so the Critic's envelope check measures the real
        object — the single source of truth holds for this leaf too.
        """
        if self.fixing == ShelfFixing.FRENCH_CLEAT:
            return self.thickness + self.cleat_height
        if self.fixing == ShelfFixing.BRACKETS:
            return self.thickness + self.bracket_height
        return self.thickness

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.fixing, Enum):
            d["fixing"] = self.fixing.value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WallShelfSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("length", "depth", "thickness", "mount_height"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "WallShelfSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class BoxSpec:
    """A six-board box / chest: four sides, a bottom, and a lid.

    The corner joint reuses the drawer-box :class:`CornerJoint` vocabulary
    (dovetail / box / locking_rabbet / rabbet / butt). An optional hinged lid
    adds hinges. Coordinates match the shared frame: X = width, Y = depth,
    Z = height; the box sits on the floor (Z=0 at its base).
    """

    kind: str = "box"
    units: str = "mm"
    name: str = "Box"
    width: float = 600.0         # X (left-right)
    depth: float = 400.0         # Y (front-back)
    height: float = 350.0        # Z (overall, including lid)
    thickness: float = 18.0      # side/bottom/lid board thickness
    corner_joint: CornerJoint = CornerJoint.DOVETAIL
    lid: bool = True             # a hinged lid on top (vs. an open box)
    hinges: int = 2              # lid hinge count (lid only)

    # --- finishing / material (optional) --------------------------------------
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = "solid"
    species: str = ""

    def __post_init__(self) -> None:
        self.corner_joint = _coerce_enum(CornerJoint, self.corner_joint)

    @property
    def body_height(self) -> float:
        """Height of the box body below the lid (Z)."""
        return self.height - (self.thickness if self.lid else 0.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.corner_joint, Enum):
            d["corner_joint"] = self.corner_joint.value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoxSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "thickness"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "BoxSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class BenchSpec:
    """A bench / stool: a seat on four legs joined by aprons and stretchers.

    Largely a low :class:`TableSpec` with leg stretchers added for a piece that
    takes a sitting load. Kept a standalone leaf (rather than refactoring a
    shared ``LeggedSpec`` base under TableSpec) so the existing table outputs are
    untouched; the shared base is a follow-up. Coordinates match the shared
    frame: X = length, Y = depth (seat width), Z = height (floor to seat top).
    """

    kind: str = "bench"
    units: str = "mm"
    name: str = "Bench"
    width: float = 1200.0        # length of the seat (X)
    depth: float = 350.0         # depth of the seat (Y)
    height: float = 450.0        # floor to seat surface (Z); ~450 bench, ~750 stool
    top_thickness: float = 30.0
    leg: float = 45.0            # square leg cross-section
    apron_height: float = 70.0
    apron_thickness: float = 20.0
    leg_inset: float = 35.0      # leg outer face set in from the seat edge
    stretchers: bool = True      # lower rails between the legs (rack resistance)
    stretcher_height: float = 30.0     # stretcher cross-section (Z)
    stretcher_thickness: float = 20.0  # stretcher cross-section (Y/X)
    stretcher_setback: float = 120.0   # stretcher centre height off the floor

    # --- material/movement (optional; defaults describe a well-built seat) -----
    solid_top: bool = True
    top_fixing: TopFixing = TopFixing.FLOATING
    grain: Grain = Grain.FLATSAWN
    joinery: Joinery = Joinery.MORTISE_TENON
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = ""      # usually "solid"
    species: str = ""            # wood species, e.g. oak | maple | ash

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
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "top_thickness", "leg",
                          "apron_height", "apron_thickness", "leg_inset",
                          "stretcher_height", "stretcher_thickness",
                          "stretcher_setback"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "BenchSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class FrameSpec:
    """A picture / mirror frame: four mitered rails with a rabbet for glazing.

    The four rails of ``molding_width`` × ``molding_thickness`` stock surround a
    visible **opening** (the sight size). A rabbet cut into the inner-back edge
    holds the glazing, the art/mirror, and a backer. Coordinates match the shared
    frame: X = width (centred), Y = depth (front face at 0, +Y toward the wall),
    Z = height (frame foot at 0). A frame is thin in Y — it hangs flat.

    Sizing convention: the rail face width (``molding_width``) is added all the
    way around the opening, so ``outer_width = opening_w + 2*molding_width``. The
    glazing/backer span the opening plus the rabbet overlap on each side.
    """

    kind: str = "frame"
    units: str = "mm"
    name: str = "Picture frame"
    opening_w: float = 400.0       # visible opening width (sight size, X)
    opening_h: float = 500.0       # visible opening height (sight size, Z)
    molding_width: float = 40.0    # rail face width (sight edge to outer edge)
    molding_thickness: float = 20.0  # rail thickness, front-to-back (Y)
    rabbet_width: float = 8.0      # ledge the glazing/art rests on (overlaps it)
    rabbet_depth: float = 10.0     # depth of the rabbet into the rail (< thickness)
    corner_joint: FrameJoint = FrameJoint.SPLINED_MITER
    contents: FrameContents = FrameContents.ART
    glazing: str = "glass"         # glass | acrylic | none
    hanger: FrameHanger = FrameHanger.D_RING_WIRE

    # --- finishing / material (optional) --------------------------------------
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = "solid"   # frame molding is solid stock
    species: str = ""              # wood species, e.g. oak | walnut | maple

    def __post_init__(self) -> None:
        self.corner_joint = _coerce_enum(FrameJoint, self.corner_joint)
        self.contents = _coerce_enum(FrameContents, self.contents)
        self.hanger = _coerce_enum(FrameHanger, self.hanger)

    @property
    def outer_w(self) -> float:
        """Overall outer width (X): opening plus a rail face on each side."""
        return self.opening_w + 2 * self.molding_width

    @property
    def outer_h(self) -> float:
        """Overall outer height (Z): opening plus a rail face top and bottom."""
        return self.opening_h + 2 * self.molding_width

    @property
    def glazing_w(self) -> float:
        """Glazing/backer width: the opening plus the rabbet overlap each side."""
        return self.opening_w + 2 * self.rabbet_width

    @property
    def glazing_h(self) -> float:
        return self.opening_h + 2 * self.rabbet_width

    # Placement aliases so a frame drops into a Project like any other leaf.
    @property
    def width(self) -> float:
        return self.outer_w

    @property
    def depth(self) -> float:
        return self.molding_thickness

    @property
    def height(self) -> float:
        return self.outer_h

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("corner_joint", "contents", "hanger"):
            if isinstance(getattr(self, k), Enum):
                d[k] = getattr(self, k).value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FrameSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("opening_w", "opening_h", "molding_width",
                          "molding_thickness", "rabbet_width", "rabbet_depth"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "FrameSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class BedSpec:
    """A knock-down bed: a headboard and footboard joined by two side rails.

    The headboard and footboard are post-and-panel frames (a frame-and-panel
    infill, reusing the door engine's vocabulary, or a slab/open panel); two
    side rails connect them with knock-down hardware (bed bolts or hook plates)
    and carry a ledger that supports a deck of cross slats. Coordinates match the
    shared frame: X = width (across the bed, centred), Y = length (head at 0,
    foot at +Y), Z = height (floor at 0).
    """

    kind: str = "bed"
    units: str = "mm"
    name: str = "Bed"
    size: BedSize = BedSize.QUEEN
    mattress_w: float = 0.0        # explicit mattress width (size="custom" or override)
    mattress_l: float = 0.0        # explicit mattress length
    clearance: float = 6.0         # gap each side between mattress and rail

    post: float = 75.0             # square post cross-section
    head_height: float = 1100.0    # head post height off the floor (Z)
    foot_height: float = 500.0     # foot post height off the floor (Z)
    deck_height: float = 250.0     # top of the side rail / slat deck off the floor

    rail_height: float = 150.0     # side-rail face height (Z)
    rail_thickness: float = 30.0   # side-rail thickness (X)
    panel: bool = True             # frame-and-panel head/foot infill (else open)
    slats: int = 0                 # cross-slat count (0 = auto from the length)

    connector: BedConnector = BedConnector.BED_BOLT

    # --- finishing / material (optional) --------------------------------------
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = "solid"
    species: str = ""              # wood species, e.g. oak | walnut | maple

    def __post_init__(self) -> None:
        self.size = _coerce_enum(BedSize, self.size)
        self.connector = _coerce_enum(BedConnector, self.connector)

    def _mattress(self) -> tuple[float, float]:
        if self.size in MATTRESS_SIZES:
            return MATTRESS_SIZES[self.size]
        return (self.mattress_w, self.mattress_l)

    @property
    def mattress_width(self) -> float:
        return self._mattress()[0]

    @property
    def mattress_length(self) -> float:
        return self._mattress()[1]

    @property
    def inner_width(self) -> float:
        """Clear width between the side rails (mattress + clearance each side)."""
        return self.mattress_width + 2 * self.clearance

    @property
    def width(self) -> float:
        """Overall outside width (X): inner clear + a rail and post each side."""
        return self.inner_width + 2 * self.rail_thickness

    @property
    def depth(self) -> float:
        """Overall length head-to-foot (Y): mattress length + post depths."""
        return self.mattress_length + 2 * self.post

    @property
    def height(self) -> float:
        """Overall height (Z) — the head post is the tallest part."""
        return self.head_height

    @property
    def slat_count(self) -> int:
        if self.slats > 0:
            return self.slats
        # ~ one slat every 100mm of mattress length keeps a foam/spring mattress
        # supported; round to a sensible minimum.
        return max(int(self.mattress_length // 100), 3)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("size", "connector"):
            if isinstance(getattr(self, k), Enum):
                d[k] = getattr(self, k).value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BedSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("mattress_w", "mattress_l", "clearance", "post",
                          "head_height", "foot_height", "deck_height",
                          "rail_height", "rail_thickness"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "BedSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class CuttingBoardSpec:
    """A glued-up cutting / charcuterie board: N strips edge-glued into a panel.

    The board is one edge-glued panel of ``strips`` strips; ``species`` (and an
    optional ``species_b``) drive an alternating pattern. End-grain boards are a
    two-stage glue-up (glue strips, crosscut, rotate 90°, re-glue) — modelled as
    the same finished panel with the extra steps called out. Coordinates match
    the shared frame: X = width (strips run across it), Y = length, Z = thickness.
    """

    kind: str = "cutting_board"
    units: str = "mm"
    name: str = "Cutting board"
    length: float = 450.0          # Y (long dimension)
    width: float = 300.0           # X (across the strips)
    thickness: float = 38.0        # Z (board thickness)
    grain_style: GrainStyle = GrainStyle.EDGE_GRAIN
    strips: int = 0                # strip count (0 = auto from width)
    juice_groove: bool = False     # a routed perimeter groove to catch juices
    feet: bool = False             # rubber/silicone feet on the underside
    chamfer: float = 4.0           # eased edge / chamfer

    # --- material/finish (food-safe by default) -------------------------------
    species: str = "hard_maple"    # primary strip species
    species_b: str = ""            # optional alternating species (e.g. walnut)
    finish: str = "oil"            # food-safe oil/board butter by default
    finish_sheen: str = "satin"
    material_form: str = "solid"

    def __post_init__(self) -> None:
        self.grain_style = _coerce_enum(GrainStyle, self.grain_style)

    @property
    def strip_count(self) -> int:
        if self.strips > 0:
            return self.strips
        # ~ one strip per 38mm of width, at least three for a glue-up.
        return max(int(self.width // 38), 3)

    @property
    def strip_width(self) -> float:
        return self.width / self.strip_count

    # Placement aliases (a board can sit in a Project like any leaf).
    @property
    def height(self) -> float:
        return self.thickness

    @property
    def depth(self) -> float:
        return self.length

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.grain_style, Enum):
            d["grain_style"] = self.grain_style.value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CuttingBoardSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("length", "width", "thickness", "chamfer"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "CuttingBoardSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class NightstandSpec:
    """A small legged cabinet: a top on four legs/aprons with a drawer + shelf.

    A table superset carrying one or two apron-hung drawers and an optional lower
    shelf. Coordinates match the shared frame: X = width, Y = depth (front at
    -Y), Z = height (top surface at ``height``).
    """

    kind: str = "nightstand"
    units: str = "mm"
    name: str = "Nightstand"
    width: float = 450.0
    depth: float = 400.0
    height: float = 600.0
    top_thickness: float = 20.0
    leg: float = 40.0              # square leg cross-section
    leg_inset: float = 25.0        # leg outer face in from the top edge
    apron_height: float = 90.0
    apron_thickness: float = 20.0
    drawers: int = 1               # stacked apron-hung drawers (0-2)
    drawer_front_height: float = 130.0
    shelf: bool = True             # a lower shelf between the legs
    shelf_thickness: float = 18.0
    shelf_setback: float = 120.0   # shelf height off the floor
    joinery: Joinery = Joinery.MORTISE_TENON
    pull: str = "knob"             # knob | bar | none

    solid_top: bool = True
    top_fixing: TopFixing = TopFixing.FLOATING
    grain: Grain = Grain.FLATSAWN
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = ""
    species: str = ""

    def __post_init__(self) -> None:
        self.joinery = _coerce_enum(Joinery, self.joinery)
        self.top_fixing = _coerce_enum(TopFixing, self.top_fixing)
        self.grain = _coerce_enum(
            Grain, self.grain, aliases={"quarter": "quartersawn",
                                        "flat": "flatsawn"})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("joinery", "top_fixing", "grain"):
            if isinstance(getattr(self, k), Enum):
                d[k] = getattr(self, k).value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NightstandSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "top_thickness", "leg",
                          "leg_inset", "apron_height", "apron_thickness",
                          "drawer_front_height", "shelf_thickness",
                          "shelf_setback"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "NightstandSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class DeskSpec:
    """A writing desk: a top on four legs/aprons with apron-hung drawer(s).

    A wider legged piece with an optional back **modesty panel** and a **cable
    grommet** in the top. Coordinates match the shared frame: X = width (length),
    Y = depth, Z = height (top at ``height``); the front is at -Y.
    """

    kind: str = "desk"
    units: str = "mm"
    name: str = "Desk"
    width: float = 1200.0
    depth: float = 600.0
    height: float = 740.0
    top_thickness: float = 25.0
    leg: float = 60.0
    leg_inset: float = 40.0
    apron_height: float = 90.0
    apron_thickness: float = 20.0
    drawers: int = 1               # apron-hung drawers across the front (0-3)
    drawer_front_height: float = 100.0
    modesty_panel: bool = True     # a back privacy panel between the legs
    modesty_height: float = 250.0
    grommet: bool = True           # a cable grommet bored in the top
    grommet_dia: float = 60.0
    joinery: Joinery = Joinery.MORTISE_TENON
    pull: str = "bar"

    solid_top: bool = True
    top_fixing: TopFixing = TopFixing.FLOATING
    grain: Grain = Grain.FLATSAWN
    finish: str = "none"
    finish_sheen: str = "satin"
    material_form: str = ""
    species: str = ""

    def __post_init__(self) -> None:
        self.joinery = _coerce_enum(Joinery, self.joinery)
        self.top_fixing = _coerce_enum(TopFixing, self.top_fixing)
        self.grain = _coerce_enum(
            Grain, self.grain, aliases={"quarter": "quartersawn",
                                        "flat": "flatsawn"})

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("joinery", "top_fixing", "grain"):
            if isinstance(getattr(self, k), Enum):
                d[k] = getattr(self, k).value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeskSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "top_thickness", "leg",
                          "leg_inset", "apron_height", "apron_thickness",
                          "drawer_front_height", "modesty_height", "grommet_dia"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "DeskSpec":
        return cls.from_dict(json.loads(text))


@dataclass
class WorkbenchSpec:
    """A heavy workbench: a thick laminated top on a stout leg-and-stretcher base.

    A beefed-up bench with a row of bench-dog holes, an optional vise, and a
    tool shelf between the stretchers. Coordinates match the shared frame:
    X = width (length), Y = depth, Z = height (top surface at ``height``).
    """

    kind: str = "workbench"
    units: str = "mm"
    name: str = "Workbench"
    width: float = 1500.0          # bench length (X)
    depth: float = 600.0
    height: float = 900.0          # working height to the top surface
    top_thickness: float = 75.0    # thick laminated top
    top_laminations: int = 0       # strips in the top glue-up (0 = auto)
    leg: float = 90.0              # heavy square legs
    leg_inset: float = 60.0
    apron_height: float = 120.0
    apron_thickness: float = 30.0
    stretchers: bool = True
    stretcher_height: float = 100.0
    stretcher_thickness: float = 30.0
    stretcher_setback: float = 200.0   # stretcher height off the floor
    dog_holes: int = 0             # bench-dog holes along the front (0 = auto)
    dog_hole_dia: float = 19.0     # 3/4in round dogs
    vise: bool = True
    vise_side: str = "left"        # left | right | front | none
    shelf: bool = True             # tool shelf on the stretchers
    shelf_thickness: float = 18.0
    joinery: Joinery = Joinery.MORTISE_TENON
    finish: str = "oil"
    finish_sheen: str = "satin"
    material_form: str = "solid"
    species: str = "beech"         # a hard, tough bench wood

    def __post_init__(self) -> None:
        self.joinery = _coerce_enum(Joinery, self.joinery)

    @property
    def dog_hole_count(self) -> int:
        if self.dog_holes > 0:
            return self.dog_holes
        # ~ one dog hole every 150mm along the usable front, at least four.
        return max(int((self.width - 2 * self.leg_inset) // 150), 4)

    @property
    def lamination_count(self) -> int:
        if self.top_laminations > 0:
            return self.top_laminations
        # Laminate ~38mm strips on edge across the depth.
        return max(int(self.depth // 38), 4)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.joinery, Enum):
            d["joinery"] = self.joinery.value
        d["schema_version"] = SCHEMA_VERSION
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkbenchSpec":
        data = dict(data)
        if normalize_unit(data.get("units")) == IMPERIAL:
            _to_mm(data, ("width", "depth", "height", "top_thickness", "leg",
                          "leg_inset", "apron_height", "apron_thickness",
                          "stretcher_height", "stretcher_thickness",
                          "stretcher_setback", "dog_hole_dia", "shelf_thickness"))
            data["units"] = "mm"
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "WorkbenchSpec":
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
        d["schema_version"] = SCHEMA_VERSION
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
        # Declarative layout: a `runs` block lays its items end-to-end along a
        # wall (via place_run), so the author expresses intent ("a row on this
        # wall") and the loader computes each x/y/rotation. Runs are appended
        # after any explicit components; on save the group serializes back to
        # resolved components (runs are an input convenience, not stored).
        for run in (data.get("runs") or []):
            comps.extend(_run_components(run, defs, _stack))
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


def _plan_width(spec) -> float:
    """The piece's extent *along the wall* for run-stepping.

    A leaf steps by its ``width``. A sub-assembly has no single width, so it
    steps by the X-extent of its placed children (``geometry.local_plan_bounds``,
    imported lazily to avoid a module cycle).
    """
    if isinstance(spec, ComponentGroup):
        from .geometry import local_plan_bounds
        x0, x1, _, _ = local_plan_bounds(spec)
        return x1 - x0
    return float(getattr(spec, "width", 0.0) or 0.0)


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
    overlapping. Leave a gap (or drop in a corner unit) where two runs meet. A
    placed piece may be a leaf or a sub-:class:`Assembly`; a group steps by its
    plan extent along the wall (it has no single ``width``).
    """
    ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out: list[Component] = []
    cursor = 0.0
    for i, spec in enumerate(specs):
        w = _plan_width(spec)
        out.append(Component(
            spec=spec, x=start[0] + ux * cursor, y=start[1] + uy * cursor,
            rotation=angle,
            label=(labels[i] if labels and i < len(labels) else "")))
        cursor += w + gap
    return out


# --- the one furniture taxonomy --------------------------------------------
# Every "what kind of thing is this spec" decision in the pipeline derives from
# this single table, so adding a furniture type is one new row here (plus the
# spec class and its ``furniture.register`` stages) — not edits to three
# hand-synced ladders (the loader below, ``KNOWN_KINDS``, and
# ``dispatch.spec_kind``).
#
# Each row is ``(canonical kind, leaf spec class, alias kinds)``. Leaf classes
# are disjoint (no inheritance between them), so ``dispatch.spec_kind`` can map
# ``type(spec) -> kind`` directly. ``CabinetSpec`` is the default leaf. The
# aggregate/placeholder kinds (project / assembly / appliance_void) are not plain
# leaves — they have their own ``from_dict`` signatures and dispatch — so they
# live in ``_GROUP_KINDS`` and are handled explicitly by the loader.
LEAF_SPEC_TYPES: tuple[tuple[str, type, tuple[str, ...]], ...] = (
    ("table", TableSpec, ()),
    ("wall_shelf", WallShelfSpec, ()),
    ("box", BoxSpec, ("chest",)),
    ("bench", BenchSpec, ("stool",)),
    ("frame", FrameSpec, ()),
    ("bed", BedSpec, ()),
    ("cutting_board", CuttingBoardSpec, ("board",)),
    ("nightstand", NightstandSpec, ()),
    ("desk", DeskSpec, ()),
    ("workbench", WorkbenchSpec, ()),
    ("cabinet", CabinetSpec, ()),
)

_GROUP_KINDS = ("project", "assembly", "appliance_void")

# kind-or-alias -> leaf class (the loader's dispatch table).
_LEAF_BY_KIND: dict[str, type] = {
    k: cls for kind, cls, aliases in LEAF_SPEC_TYPES for k in (kind, *aliases)
}

# Discriminators the loader recognizes. A spec *without* a ``kind`` still routes
# by shape — every stored cabinet/table/project predates the field, so the
# heuristic fallback keeps them loading. A spec that names an **unknown** kind is
# rejected (rather than silently built as a cabinet) so a hallucinated type
# surfaces as a repairable error in the designer loop. Derived from the table
# above so it can never drift from what the loader actually accepts.
KNOWN_KINDS = frozenset(set(_LEAF_BY_KIND) | set(_GROUP_KINDS))

# Stamped onto every serialized spec (see ``to_dict``) so a future breaking
# change has something to branch on. Accepted and ignored on input.
SCHEMA_VERSION = "1.0"


def _run_components(run: dict, defs: "_Defs", stack: frozenset) -> list[Component]:
    """Expand one declarative ``run`` block into placed :class:`Component`s.

    A run is ``{"start": [x, y], "angle": deg, "gap": mm, "items": [...]}`` where
    each item is a component dict (``spec`` inline or a ``ref``). The items'
    specs are laid end-to-end by :func:`place_run`; any ``x``/``y`` on an item is
    ignored — the run computes placement. An item's ``label`` is kept; otherwise
    a run-level ``labels`` list is used.
    """
    if not isinstance(run, dict):
        return []
    specs: list[Any] = []
    labels: list[str] = []
    for it in (run.get("items") or []):
        if not isinstance(it, dict):
            continue
        comp = _component_from_dict(it, defs, stack)
        specs.append(comp.spec)
        labels.append(comp.label)
    start = run.get("start", (0.0, 0.0))
    if isinstance(start, (list, tuple)) and len(start) >= 2:
        start = (float(start[0]), float(start[1]))
    else:
        start = (0.0, 0.0)
    if not any(labels):
        labels = [str(v) for v in (run.get("labels") or [])]
    return place_run(
        specs, start=start, angle=float(run.get("angle", 0.0)),
        gap=float(run.get("gap", 0.0)), labels=labels or None,
    )


def _spec_from_dict(data: dict[str, Any], defs: "_Defs | None", stack: frozenset):
    """Pick the right spec, threading the definition registry into groups.

    ``kind`` is the explicit discriminator; a named-but-unknown kind raises
    ``ValueError`` instead of falling through to a cabinet. When ``kind`` is
    absent the spec is routed by shape for backward compatibility.
    """
    kind = str(data.get("kind", "")).strip().lower()
    if kind and kind not in KNOWN_KINDS:
        raise ValueError(
            f"unknown kind {kind!r}; expected one of "
            f"{', '.join(sorted(KNOWN_KINDS))}")
    # Aggregates / placeholders have bespoke from_dict signatures and dispatch.
    if kind == "appliance_void":
        return ApplianceVoid.from_dict(data)
    if kind == "assembly":
        return Assembly.from_dict(data, parent_defs=defs, _stack=stack)
    if kind == "project" or "components" in data or "runs" in data:
        return Project.from_dict(data, parent_defs=defs, _stack=stack)
    # Every plain leaf type (and its aliases) routes through the one taxonomy.
    leaf = _LEAF_BY_KIND.get(kind)
    if leaf is not None:
        return leaf.from_dict(data)
    # No explicit kind: infer a table from its tell-tale fields, else a cabinet.
    if "leg" in data or "top_thickness" in data:
        return TableSpec.from_dict(data)
    return CabinetSpec.from_dict(data)


def joinery_key(spec, default: str = "") -> str:
    """A spec's joinery as a normalized lowercase string.

    The one place that decodes the :class:`Joinery` enum (or a raw string) for the
    call sites that *key a lookup table or a message* off the joinery — so they
    don't each re-spell ``str(spec.joinery).strip().lower()`` (where a stray
    variation could quietly diverge). Returns *default* when the spec has no
    joinery field.
    """
    return str(getattr(spec, "joinery", default)).strip().lower()


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
Output ONE furniture spec as a JSON object. Set "units" to "mm" (default) or
"in"; give every dimension in that unit and do not mix — inches are converted to
millimetres on load.

STEP 1 — choose the "kind" first, then fill in that type's fields below:
  "cabinet"     a single box of casework (use "cabinet_type" for the variant)
  "table"       a top on four legs + aprons
  "wall_shelf"  one board fixed to the wall
  "box"         a six-board box / chest
  "bench"       a seat on legs (a low table; "stool" too)
  "frame"       a picture / mirror frame (four mitered rails + a rabbet)
  "bed"         a knock-down bed (headboard + footboard + rails + slats)
  "cutting_board" a glued-up cutting / charcuterie board (edge/end grain)
  "nightstand"  a small legged cabinet with a drawer + lower shelf
  "desk"        a writing desk (legs + apron drawer + modesty panel)
  "workbench"   a heavy bench: thick top, stretchers, dog holes, a vise
  "project"     more than one piece — a run / built-in (place components)

STEP 2 — copy the matching MINIMAL example, then adjust. Every field not shown
has a sensible default, so a minimal spec is already buildable; add fields only
to override a default.

-- minimal cabinet -------------------------------------------------------------
{{"kind": "cabinet", "cabinet_type": "base", "name": "Base", "width": 600,
 "height": 720, "depth": 560, "doors": 2, "shelves": 1}}
-- minimal table ---------------------------------------------------------------
{{"kind": "table", "name": "Table", "width": 1200, "depth": 750, "height": 740}}
-- minimal wall shelf ----------------------------------------------------------
{{"kind": "wall_shelf", "name": "Shelf", "length": 800, "depth": 200,
 "thickness": 25, "fixing": "french_cleat"}}
-- minimal box -----------------------------------------------------------------
{{"kind": "box", "name": "Box", "width": 600, "depth": 400, "height": 350,
 "thickness": 18, "corner_joint": "dovetail", "lid": true}}
-- minimal bench ---------------------------------------------------------------
{{"kind": "bench", "name": "Bench", "width": 1200, "depth": 350, "height": 450}}
-- minimal frame ---------------------------------------------------------------
{{"kind": "frame", "name": "Frame", "opening_w": 400, "opening_h": 500,
 "molding_width": 40, "corner_joint": "splined_miter"}}
-- minimal bed -----------------------------------------------------------------
{{"kind": "bed", "name": "Bed", "size": "queen", "connector": "bed_bolt"}}
-- minimal cutting board -------------------------------------------------------
{{"kind": "cutting_board", "name": "Board", "length": 450, "width": 300,
 "thickness": 38, "grain_style": "edge_grain", "species": "hard_maple"}}
-- minimal nightstand ----------------------------------------------------------
{{"kind": "nightstand", "name": "Nightstand", "width": 450, "depth": 400,
 "height": 600, "drawers": 1}}
-- minimal desk ----------------------------------------------------------------
{{"kind": "desk", "name": "Desk", "width": 1200, "depth": 600, "height": 740,
 "drawers": 1}}
-- minimal workbench -----------------------------------------------------------
{{"kind": "workbench", "name": "Workbench", "width": 1500, "depth": 600,
 "height": 900, "vise": true}}
-- minimal project (a row of two cabinets via a declarative run) ----------------
{{"kind": "project", "name": "Run", "runs": [
  {{"start": [0, 0], "angle": 0, "gap": 0, "items": [
    {{"spec": {{"kind": "cabinet", "cabinet_type": "base", "width": 600}}}},
    {{"spec": {{"kind": "cabinet", "cabinet_type": "base", "width": 800}}}}]}}]}}

Full field reference for each kind follows.

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
  "finish": "none" | "oil" | "clear" | "paint" | "stain_clear",
  // --- material make-up (ALL OPTIONAL) -------------------------------------
  // Declare what the piece is made of to drive the shopping list, the quote,
  // and build hints. Omit everything and it's treated as one generic sheet good.
  "material_form": "plywood" | "mdf" | "particleboard" | "melamine" |
                   "hardboard" | "solid",   // whole-piece default form
  "species": "oak" | "maple" | "pine" | "birch" | "walnut" | ...,  // wood species
  "stock": {{     // optional per-area overrides (each form?/species?); areas:
                 // carcass | back | shelf | front | door_panel | drawer_box | frame
    "front": {{"form": "solid", "species": "oak"}},
    "frame": {{"form": "solid", "species": "oak"}}
  }},
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
  "joinery": {_opts(Joinery)},
  "material_form": "solid" | "plywood" | ...,   // optional; default treats top as sheet
  "species": "walnut" | "oak" | ...             // optional wood species
}}

== WALL SHELF ==
A single board fixed to the wall by a French cleat or a pair of brackets.
{{
  "kind": "wall_shelf",
  "name": "Oak Shelf",
  "units": "mm",
  "length": <along the wall>,
  "depth": <out from the wall, e.g. 200>,
  "thickness": <board thickness, e.g. 25>,
  "mount_height": <where the shelf top hangs off the floor, e.g. 1400>,
  "fixing": {_opts(ShelfFixing)},
  "brackets": <bracket count when fixing="brackets", >=2>,
  "load_kg_per_m": <expected load along the shelf, e.g. 15 (books ~20-40)>,
  "material_form": "solid" | "plywood" | ...,   // optional
  "species": "oak" | "pine" | "walnut" | ...,   // optional wood species
  "finish": "none" | "oil" | "clear" | "paint" | "stain_clear"
}}
The validator checks the shelf for sag (deflection vs span/360) from the length,
depth, thickness, species and load — thicken the board, use a stiffer species,
or add a center bracket for a long or heavily-loaded shelf.

== BOX / CHEST ==
A six-board box: four sides, a captured bottom, and an optional hinged lid.
{{
  "kind": "box",
  "name": "Blanket Chest",
  "units": "mm",
  "width": <left-right>,
  "depth": <front-back>,
  "height": <overall, including the lid>,
  "thickness": <side/bottom/lid board thickness, e.g. 18>,
  "corner_joint": {_opts(CornerJoint)},
  "lid": true | false,
  "hinges": <lid hinge count when lid=true, >=2>,
  "material_form": "solid" | "plywood" | ...,   // optional
  "species": "walnut" | "oak" | "pine" | ...,   // optional wood species
  "finish": "none" | "oil" | "clear" | "paint" | "stain_clear"
}}
Box corners should be "dovetail", "box", or a locking rabbet (a "butt" corner is
weak and pulls apart); the bottom rides in a groove. A hinged lid takes butt
hinges (and usually a lid stay).

== BENCH / STOOL ==
A seat on four legs joined by aprons and (for rack resistance) lower stretchers.
A low table superset — use for a dining bench (~430mm) or a stool (~650mm).
{{
  "kind": "bench",
  "name": "Dining Bench",
  "units": "mm",
  "width": <length of the seat>,
  "depth": <depth of the seat, e.g. 350>,
  "height": <floor to seat surface; bench ~430, stool ~650>,
  "top_thickness": 30,
  "leg": <square leg cross-section, e.g. 45>,
  "apron_height": 70,
  "apron_thickness": 20,
  "leg_inset": <leg outer face set in from the seat edge, e.g. 35>,
  "stretchers": true | false,        // lower rails between the legs
  "joinery": {_opts(Joinery)},       // mortise_tenon / domino resist racking
  "material_form": "solid" | ...,    // optional
  "species": "oak" | "maple" | "ash" | ...   // optional wood species
}}
Keep mortise_tenon or domino leg joints and the stretchers for a seat that takes
a sitting load; a tall stool without stretchers racks.

== FRAME (picture / mirror) ==
Four rails of molding around a visible opening, mitered at the corners, with a
rabbet cut into the inner-back edge to hold the glazing, art/mirror, and backer.
{{
  "kind": "frame",
  "name": "Mirror Frame",
  "units": "mm",
  "opening_w": <visible opening width (sight size)>,
  "opening_h": <visible opening height (sight size)>,
  "molding_width": <rail face width, e.g. 40>,
  "molding_thickness": <rail thickness front-to-back, e.g. 20>,
  "rabbet_width": <ledge the glazing rests on, e.g. 8>,
  "rabbet_depth": <rabbet depth into the rail (< molding_thickness), e.g. 10>,
  "corner_joint": {_opts(FrameJoint)},
  "contents": {_opts(FrameContents)},
  "glazing": "glass" | "acrylic" | "none",
  "hanger": {_opts(FrameHanger)},
  "material_form": "solid",                  // frame molding is solid stock
  "species": "oak" | "walnut" | "maple" | ...,  // optional wood species
  "finish": "none" | "oil" | "clear" | "paint" | "stain_clear"
}}
The outer size is the opening plus a rail face all around
(outer = opening + 2·molding_width). A plain glued "miter" is end-grain-weak —
prefer "splined_miter" or "half_lap", especially on larger frames; the rabbet
must be shallower than the molding is thick. A mirror is heavy: hang it with
D-rings + wire or a cleat into a stud, not a single sawtooth.

== BED ==
A knock-down bed: a headboard and footboard (post-and-panel) joined by two side
rails with bed bolts or hook plates, carrying a deck of cross slats.
{{
  "kind": "bed",
  "name": "Walnut Platform Bed",
  "units": "mm",
  "size": {_opts(BedSize)},   // "custom" => give mattress_w + mattress_l
  "mattress_w": <custom mattress width>,   "mattress_l": <custom mattress length>,
  "clearance": <gap each side, mattress to rail, e.g. 6>,
  "post": <square post cross-section, e.g. 75>,
  "head_height": <head post height off the floor, e.g. 1100>,
  "foot_height": <foot post height off the floor, e.g. 500>,
  "deck_height": <slat-deck height off the floor, e.g. 250>,
  "rail_height": 150, "rail_thickness": 30,
  "panel": true | false,             // frame-and-panel head/foot infill
  "slats": <cross-slat count, 0 = auto (~every 100mm)>,
  "connector": {_opts(BedConnector)},  // knock-down rail joinery
  "material_form": "solid",
  "species": "walnut" | "oak" | "maple" | ...,
  "finish": "none" | "oil" | "clear" | "paint" | "stain_clear"
}}
Beds must come apart to move, so the rails join the posts with knock-down
hardware (bed bolts / hook plates), never glue. Size from a standard mattress or
set "custom" with explicit mattress dimensions; the deck takes enough slats to
support the mattress.

== CUTTING BOARD ==
A glued-up cutting / charcuterie board: N strips edge-glued into one panel.
{{
  "kind": "cutting_board",
  "name": "Maple & Walnut Board",
  "units": "mm",
  "length": <long dimension, e.g. 450>,
  "width": <across the strips, e.g. 300>,
  "thickness": <board thickness, e.g. 38>,
  "grain_style": {_opts(GrainStyle)},  // end_grain = butcher block (knife-kind)
  "strips": <strip count, 0 = auto (~1 per 38mm)>,
  "juice_groove": true | false,
  "feet": true | false,
  "species": "hard_maple" | "walnut" | "cherry" | ...,   // primary strip
  "species_b": "walnut" | "",          // optional alternating second species
  "finish": "oil"                       // food-safe oil / board butter
}}
End-grain boards are a two-stage glue-up (glue strips, crosscut, rotate, re-glue)
and want a thicker blank. Use a food-safe finish (mineral oil / board butter),
not a film finish. Avoid very open-pore woods (oak) for a board.

== NIGHTSTAND ==
A small legged cabinet: a top on four legs/aprons with apron-hung drawer(s) and
an optional lower shelf.
{{
  "kind": "nightstand",
  "name": "Walnut Nightstand",
  "units": "mm",
  "width": <e.g. 450>, "depth": <e.g. 400>, "height": <e.g. 600>,
  "top_thickness": 20,
  "leg": <square leg, e.g. 40>, "leg_inset": <from the top edge, e.g. 25>,
  "apron_height": 90, "apron_thickness": 20,
  "drawers": <0-2 stacked drawers>,
  "drawer_front_height": 130,
  "shelf": true | false, "shelf_setback": <shelf height off floor, e.g. 120>,
  "joinery": {_opts(Joinery)},      // leg-to-apron: mortise_tenon/domino resist racking
  "pull": "knob" | "bar" | "none",
  "species": "walnut" | "maple" | ..., "finish": "none" | "oil" | ...
}}

== DESK ==
A writing desk: a top on four legs/aprons with apron-hung drawer(s), an optional
back modesty panel and a cable grommet.
{{
  "kind": "desk",
  "name": "Oak Desk",
  "units": "mm",
  "width": <length, e.g. 1200>, "depth": <e.g. 600>, "height": <~740>,
  "top_thickness": 25,
  "leg": 60, "leg_inset": 40, "apron_height": 90, "apron_thickness": 20,
  "drawers": <0-3 across the front>, "drawer_front_height": 100,
  "modesty_panel": true | false, "modesty_height": 250,
  "grommet": true | false, "grommet_dia": 60,
  "joinery": {_opts(Joinery)}, "pull": "bar" | "knob" | "none",
  "species": "white_oak" | ..., "finish": "none" | "oil" | ...
}}

== WORKBENCH ==
A heavy bench: a thick laminated top on a stout leg-and-stretcher base, with a
row of bench-dog holes, an optional vise, and a tool shelf.
{{
  "kind": "workbench",
  "name": "Roubo-style Bench",
  "units": "mm",
  "width": <length, e.g. 1500>, "depth": <e.g. 600>, "height": <~900>,
  "top_thickness": <thick, e.g. 75>, "top_laminations": <0 = auto>,
  "leg": <heavy, e.g. 90>, "leg_inset": 60,
  "apron_height": 120, "apron_thickness": 30,
  "stretchers": true, "stretcher_setback": 200,
  "dog_holes": <0 = auto row along the front>, "dog_hole_dia": 19,
  "vise": true | false, "vise_side": "left" | "right" | "front" | "none",
  "shelf": true | false,
  "joinery": {_opts(Joinery)},      // mortise_tenon / domino for a bench that won't rack
  "species": "beech" | "maple" | "ash" | ..., "finish": "oil"
}}
A bench wants hard, tough wood (beech/maple/ash), draw-bored or pinned M&T joints
that won't rack under planing, and a thick top laminated from strips on edge.

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
PREFER a declarative "runs" block over hand-computed coordinates: each run lays
its "items" end-to-end along a wall and the loader computes every x/y/rotation
for you, so you never do the cumulative-width arithmetic (the #1 source of
overlap errors). A run is {{"start": [x, y], "angle": <deg, 0=+X, 90=+Y>,
"gap": <mm between pieces>, "items": [<components>]}}; an L-/U-kitchen is just
two or more runs at right angles. Drop in a "ref" item to place a definition.
Use explicit "components" with x/y only when you need a piece somewhere a run
can't express. Either way the validator checks plan collisions across the whole
run (including sub-assemblies); do not let footprints overlap.

An ASSEMBLY ("kind": "assembly") is the same shape as a project but is meant to
nest: use it for a repeated group (a drawer bank, a wall-cabinet pair) so it
moves as one unit. Place a sub-assembly either inline (a component whose "spec"
is the assembly) or by reference — declare it once under "definitions" and drop
it in many times with "ref": "<name>" (each ref is an independent copy, so give
each its own x/y). Assemblies may nest, but a reference must not form a cycle.

APPLIANCES come in two shapes by how they mount: a SINK or COOKTOP is a cutout
*hosted by a countertop* — add it to a cabinet's "accessories" as
{{"kind": "appliance", "type": "sink", ...}} alongside a "countertop". A RANGE,
DISHWASHER, or FRIDGE is a free-standing GAP in the run — place it as its own
component with {{"kind": "appliance_void", "type": "dishwasher", "width": 600}},
not a cabinet box.

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

Material make-up is optional and feeds the shopping list, the cost, and build
hints. Set "material_form"/"species" for the whole piece and override any area
with "stock". With nothing set, all sheet parts are bought as one generic sheet
good; set just a form (e.g. "plywood") to group by form; add a "species" (e.g.
"oak") and the BOM reads "Oak plywood" / "Oak solid lumber" and prices per
species. A face frame, table legs and aprons are always solid lumber, so a
sheet "material_form" never turns them into plywood — give them their own
"species". Typical: a plywood carcass with solid-wood doors and face frame —
set material_form "plywood" and species "birch", then under stock give "front"
and "frame" a form of "solid" and species "oak".

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
