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


# The schema description handed to the LLM designer agent as part of its prompt.
DSL_SCHEMA_HINT = """\
A cabinet is described by this JSON object (units default to "mm"):

{
  "cabinet_type": "base" | "wall" | "tall",
  "name": "Sink Base",
  "units": "mm",
  "width": <overall width>,
  "height": <overall height, including toe kick>,
  "depth": <overall depth>,
  "material": {"carcass": 18, "back": 6, "door": 18, "shelf": 18},
  "construction": "frameless" | "face_frame",
  "back": "rabbeted" | "applied" | "grooved",
  "joinery": "dado" | "dowel" | "domino" | "screw",
  "toe_kick": {"height": 100, "setback": 50}  | null,
  "shelves": <integer count of adjustable shelves>,
  "doors": <integer count of doors, 0, 1 or 2>,
  "drawers": [{"front_height": 140}, ...],
  "reveal": <gap in mm around overlay doors/drawers, e.g. 3>,
  "edge_banding": true | false
}

Rules of thumb by cabinet_type:
- base: floor cabinet, ~720mm box + ~100mm toe kick, 560-600mm deep. Has a toe
  kick; the top is open (rails), so a counter can sit on it.
- wall: hangs on the wall, NO toe kick (set "toe_kick": null), 300-400mm deep,
  600-900mm tall, enclosed top. Usually doors only, no drawers.
- tall: pantry/utility, floor to near ceiling (1900-2400mm), has a toe kick,
  enclosed top, many shelves.
Convert any imperial dimensions to mm (1 in = 25.4 mm).
"""
