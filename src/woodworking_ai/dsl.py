"""The furniture description language.

This module defines the *language* the AI agents write: a small, typed,
declarative spec that fully describes a piece of casework. A valid spec is the
single source of truth from which we derive geometry, a cut list, and a hardware
schedule.

The spec is plain dataclasses with JSON (de)serialization, so it has zero CAD
dependencies and can be produced, validated, diffed, and stored anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
import json


class CabinetType(str, Enum):
    BASE = "base"        # sits on the floor, toe kick, top stretchers
    WALL = "wall"        # hangs on the wall, no toe kick, full top
    TALL = "tall"        # floor-to-ceiling pantry/utility, toe kick, full top
    CORNER_BLIND = "corner_blind"        # door opening + a blind filler return
    CORNER_DIAGONAL = "corner_diagonal"  # 45° angled face with an angled door
    BOOKCASE = "bookcase"  # open shelving, enclosed top, no doors
    DRESSER = "dresser"    # a drawer bank / chest of drawers, enclosed top


class Construction(str, Enum):
    FRAMELESS = "frameless"      # Euro / frameless box
    FACE_FRAME = "face_frame"    # traditional face-frame


class BackStyle(str, Enum):
    RABBETED = "rabbeted"        # back sits in a rabbet on the sides/top/bottom
    APPLIED = "applied"          # back nailed/screwed to the rear edges
    GROOVED = "grooved"          # back captured in a groove


class Joinery(str, Enum):
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


@dataclass
class Material:
    """Sheet-good thicknesses, in the spec's units (default mm)."""
    carcass: float = 18.0
    back: float = 6.0
    door: float = 18.0
    shelf: float = 18.0
    drawer_box: float = 12.0     # drawer box sides/front/back stock


@dataclass
class ToeKick:
    height: float = 100.0
    setback: float = 50.0


@dataclass
class Drawer:
    front_height: float = 140.0
    false_front: bool = False    # a fixed panel (e.g. sink tip-out), no box
    # --- box joinery + slide hardware (optional; defaults = good practice) ----
    corner_joint: str = "dovetail"   # dovetail | box | rabbet | dowel | butt
    dovetail_tails: str = "sides"    # tails on "sides" (correct) so the front
                                     # can't pull off; "front" is wrong
    slide_type: str = "side_mount"   # side_mount | undermount
    slide_clearance: float = 12.7    # per-side gap for side-mount slides (½in)
    slide_length: float = 0.0        # nominal slide length; 0 = derive from depth


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
    center_mullion: bool = False # vertical post/stile between a pair of doors
    blind_width: float = 0.0     # corner_blind: width of the blind/filler return
    corner_cut: float = 0.0      # corner_diagonal: leg length of the 45° chamfer
    edge_banding: bool = True
    name: str = "Cabinet"

    # --- engineering inputs (optional; sensible defaults keep old specs valid) -
    shelf_species: str = "plywood"   # drives shelf stiffness for the sag check
    shelf_load_kg_per_m: float = 25.0  # distributed shelf load; ~books/dishes
    anti_tip: bool = False           # wall restraint / anti-tip hardware provided

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
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CabinetSpec":
        data = dict(data)  # don't mutate caller's dict
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
    top_fixing: str = "floating" # "floating" (movement allowed) | "fixed"
    grain: str = "flatsawn"      # "flatsawn" | "quartersawn" — affects movement
    joinery: str = "mortise_tenon"  # leg-to-apron joint; drives racking check

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_json(cls, text: str) -> "TableSpec":
        return cls.from_dict(json.loads(text))


def spec_from_dict(data: dict[str, Any]):
    """Pick the right furniture spec from a payload (cabinet vs table)."""
    kind = str(data.get("kind", "")).lower()
    if kind == "table" or "leg" in data or "top_thickness" in data:
        return TableSpec.from_dict(data)
    return CabinetSpec.from_dict(data)


# The schema description handed to the LLM designer agent as part of its prompt.
DSL_SCHEMA_HINT = """\
A cabinet is described by this JSON object (units default to "mm"):

{
  "cabinet_type": "base" | "wall" | "tall" | "corner_blind" |
                  "corner_diagonal" | "bookcase" | "dresser",
  "name": "Sink Base",
  "units": "mm",
  "width": <overall width>,
  "height": <overall height, including toe kick>,
  "depth": <overall depth>,
  "material": {"carcass": 18, "back": 6, "door": 18, "shelf": 18,
               "drawer_box": 12},
  "construction": "frameless" | "face_frame",
  "back": "rabbeted" | "applied" | "grooved",
  "joinery": "dado" | "dowel" | "domino" | "screw",
  "toe_kick": {"height": 100, "setback": 50}  | null,
  "shelves": <integer count of adjustable shelves>,
  "doors": <integer count of doors, 0, 1 or 2>,
  "drawers": [{"front_height": 140, "false_front": false,
               "corner_joint": "dovetail", "slide_type": "side_mount",
               "slide_clearance": 12.7}, ...],
  "reveal": <gap in mm around overlay doors/drawers, e.g. 3>,
  "center_mullion": <true to add a vertical post between a pair of doors>,
  "blind_width": <corner_blind only: width of the blind/filler return>,
  "corner_cut": <corner_diagonal only: leg length of the 45 degree chamfer>,
  "edge_banding": true | false,
  "shelf_species": "plywood" | "mdf" | "particleboard" | "oak" | "maple" | ...,
  "shelf_load_kg_per_m": <expected shelf load, e.g. 25 (books ~20-40)>,
  "anti_tip": true | false
}

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
system.

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
Convert any imperial dimensions to mm (1 in = 25.4 mm).
"""
