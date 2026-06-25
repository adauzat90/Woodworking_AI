"""Orderable hardware catalogue + bore geometry.

The hardware schedule and the drilling schedule both need more than a generic
"concealed hinge": they need a *specific* part (brand + SKU) and the exact
boring that part requires. This module is the single source of that knowledge.

It models four hardware families a shop actually orders:

* :class:`HingeSpec`  — 35 mm concealed (Euro) hinge + mounting plate, with the
  cup bore and the plate screw pattern; overlay / half-overlay / inset.
* :class:`SlideSpec`  — side-mount or undermount drawer slide, with the box
  width it demands and (undermount) its rear notch and locking-device holes.
* :class:`PullSpec`   — door/drawer pull with its hole spacing.
* :class:`Fastener`   — assembly hardware (Confirmat / cam-and-dowel / screws).

A small built-in catalogue covers a generic line plus Blum, Hettich and Grass.
:func:`select_hinge` / :func:`select_slide` / :func:`select_pull` pick the right
part for a brand and situation. Pure data — no CAD dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    HINGE_CUP_DIA, HINGE_CUP_DEPTH, HINGE_CUP_INSET, SYSTEM_PITCH,
    SLIDE_SIDE_CLEARANCE,
)

# 35 mm Euro hinge cup geometry — canonical values live in constants.py.
CUP_DIA = HINGE_CUP_DIA
CUP_DEPTH = HINGE_CUP_DEPTH
CUP_INSET = HINGE_CUP_INSET   # cup centre in from the door's hinge edge
PLATE_SCREW_PITCH = SYSTEM_PITCH   # the two plate screws sit on the 32 mm system
PLATE_SCREW_INSET = 37.0   # plate screw row in from the front edge of the side

KNOWN_BRANDS = ("generic", "blum", "hettich", "grass")

# Standard drawer-slide lengths a shop can actually order (metric, mm). A box is
# sized to one of these — you cannot buy an arbitrary length. Imperial slides map
# onto the same set: 18"≈450, 20"≈500, 22"≈550, 24"≈600 (also 250/300/350/400).
STANDARD_SLIDE_LENGTHS = (250.0, 300.0, 350.0, 400.0, 450.0, 500.0, 550.0, 600.0)


def longest_slide_for(max_length: float) -> float:
    """Longest standard slide length that fits within *max_length* (mm).

    Returns 0.0 when even the shortest standard slide is too long for the space.
    """
    fitting = [s for s in STANDARD_SLIDE_LENGTHS if s <= max_length]
    return max(fitting) if fitting else 0.0


def normalize_brand(brand: str | None) -> str:
    b = str(brand or "generic").strip().lower()
    return b if b in KNOWN_BRANDS else "generic"


@dataclass
class HingeSpec:
    name: str
    brand: str
    sku: str
    overlay: str = "overlay"       # overlay | half | inset
    opening_angle: int = 110
    cup_dia: float = CUP_DIA
    cup_depth: float = CUP_DEPTH
    cup_inset: float = CUP_INSET
    plate_sku: str = ""
    plate_screw_inset: float = PLATE_SCREW_INSET
    soft_close: bool = True


@dataclass
class SlideSpec:
    name: str
    brand: str
    sku: str
    slide_type: str = "side_mount"  # side_mount | undermount
    length: float = 500.0
    side_clearance: float = SLIDE_SIDE_CLEARANCE  # per side (box w = opening-2*)
    # Undermount: the box is sized to the opening less this *total* clearance,
    # needs a rear notch for the locking device, and a pair of locking holes.
    box_clearance_total: float = 42.0
    rear_notch: bool = False
    locking_holes: int = 0
    soft_close: bool = True

    def box_width(self, opening_w: float) -> float:
        """Outer drawer-box width this slide demands for *opening_w*."""
        if self.slide_type == "undermount":
            return opening_w - self.box_clearance_total
        return opening_w - 2 * self.side_clearance


@dataclass
class PullSpec:
    name: str
    brand: str
    sku: str
    hole_spacing: float = 96.0      # centre-to-centre (mm); 0 = knob (one hole)


@dataclass
class Fastener:
    name: str
    sku: str
    note: str = ""


# --- built-in catalogue ------------------------------------------------------
# Representative parts per brand. SKUs are realistic exemplars, not a live price
# list; a shop edits these in its profile. The generic line carries no SKU.
_HINGES = {
    "generic": HingeSpec("Concealed hinge 110°", "generic", "", plate_sku=""),
    "blum": HingeSpec("CLIP top BLUMOTION 110°", "blum", "71B3550",
                      plate_sku="173L6100", opening_angle=110),
    "hettich": HingeSpec("Sensys 8645i 110°", "hettich", "9071626",
                         plate_sku="9071538", opening_angle=110),
    "grass": HingeSpec("Tiomos 110°", "grass", "F017139377217",
                       plate_sku="F058139383228", opening_angle=110),
}
_SLIDES_SIDE = {
    "generic": SlideSpec("Ball-bearing slide (side)", "generic", "",
                         slide_type="side_mount"),
    "blum": SlideSpec("Blum 230M side-mount", "blum", "230M",
                      slide_type="side_mount"),
    "hettich": SlideSpec("Hettich KA 5532", "hettich", "KA5532",
                         slide_type="side_mount"),
    "grass": SlideSpec("Grass Zargen side-mount", "grass", "ZSIDE",
                       slide_type="side_mount"),
}
_SLIDES_UNDER = {
    "generic": SlideSpec("Undermount slide", "generic", "",
                         slide_type="undermount", box_clearance_total=42.0,
                         rear_notch=True, locking_holes=2),
    "blum": SlideSpec("Blum TANDEM 563H + BLUMOTION", "blum", "563H",
                      slide_type="undermount", box_clearance_total=42.0,
                      rear_notch=True, locking_holes=2),
    "hettich": SlideSpec("Hettich Quadro V6", "hettich", "QUADROV6",
                         slide_type="undermount", box_clearance_total=42.0,
                         rear_notch=True, locking_holes=2),
    "grass": SlideSpec("Grass Dynapro", "grass", "DYNAPRO",
                       slide_type="undermount", box_clearance_total=42.0,
                       rear_notch=True, locking_holes=2),
}
# Every brand currently stocks the same generic 96mm bar pull, so the part is
# built per brand rather than kept as four identical catalogue rows. (Add a real
# per-brand table here once distinct pulls are actually sourced.)
DEFAULT_PULL_SPACING = 96.0

# Carcass assembly hardware (per joinery family).
CONFIRMAT = Fastener("Confirmat screw 7×50", "CONF-7x50", "carcass assembly")
CAM_DOWEL = Fastener("Cam & dowel (RTA)", "CAM-DOWEL", "knock-down connector")
ASSEMBLY_SCREW = Fastener("Assembly screw 4×35", "SCR-4x35", "general assembly")
SHELF_PIN = Fastener("Shelf pin 5mm", "PIN-5", "supports adjustable shelf")


def select_hinge(brand: str, overlay: str = "overlay") -> HingeSpec:
    h = _HINGES[normalize_brand(brand)]
    return HingeSpec(**{**h.__dict__, "overlay": overlay})


def select_slide(brand: str, slide_type: str = "side_mount",
                 length: float = 0.0) -> SlideSpec:
    brand = normalize_brand(brand)
    table = _SLIDES_UNDER if slide_type == "undermount" else _SLIDES_SIDE
    s = table[brand]
    return SlideSpec(**{**s.__dict__, "length": length or s.length})


def select_pull(brand: str) -> PullSpec:
    brand = normalize_brand(brand)
    sku = "" if brand == "generic" else "PULL96"
    return PullSpec("Bar pull 96mm", brand, sku,
                    hole_spacing=DEFAULT_PULL_SPACING)


def hinge_count(door_height: float) -> int:
    """Number of concealed hinges for a door of this height."""
    if door_height <= 900:
        return 2
    if door_height <= 1600:
        return 3
    if door_height <= 2000:
        return 4
    return 5
