"""Shared part-dimension math.

One definition of the sizes that the geometry compiler (:mod:`geometry`) and the
cut list (:mod:`cutlist`) must agree on. Both modules used to derive these
numbers independently from the same constants, which let the 3D model and the
cut list drift apart. Keeping the arithmetic here means they cannot.

Pure arithmetic — no CAD dependency.
"""

from __future__ import annotations

from typing import NamedTuple

from .constants import (
    SLIDE_SIDE_CLEARANCE, DRAWER_BOX_HEIGHT_DROP, DRAWER_BOX_DEPTH_GAP,
    MIN_DRAWER_BOX_HEIGHT, MIN_DRAWER_BOX_DEPTH,
    DOOR_STILE_WIDTH, DOOR_RAIL_WIDTH, DOOR_PANEL_GROOVE,
    SHELF_SIDE_CLEARANCE, SHELF_SETBACK,
)
from .dsl import BackStyle


def drawer_box_dims(opening_w: float, front_height: float,
                    interior_depth: float, *,
                    width_floor: float = 0.0) -> tuple[float, float, float]:
    """Outer ``(width, height, depth)`` of a drawer box, in mm.

    The box rides side-mount slides, so its width is the opening less the slide
    clearance each side; its height sits below the drawer front; its depth is
    set back from the interior. ``width_floor`` lets the 3D model keep a
    usable-width floor — the cut list passes ``0`` (it sizes straight from the
    opening) and snaps the depth to a real standard slide length separately.
    """
    box_w = max(opening_w - 2 * SLIDE_SIDE_CLEARANCE, width_floor)
    box_h = max(front_height - DRAWER_BOX_HEIGHT_DROP, MIN_DRAWER_BOX_HEIGHT)
    box_d = max(interior_depth - DRAWER_BOX_DEPTH_GAP, MIN_DRAWER_BOX_DEPTH)
    return box_w, box_h, box_d


class DoorPanelDims(NamedTuple):
    """Sizes for the parts of a 5-piece (stile-and-rail) door leaf.

    Two views of the same door, kept consistent here so the cut list and the 3D
    model can't drift:

    * ``opening_w`` / ``opening_h`` — the *visible* frame opening between the
      stiles / rails. The 3D model tiles the leaf to these (parts touch, never
      overlap, so the Critic's interference check stays clean).
    * ``rail_length`` / ``panel_w`` / ``panel_h`` — the *cut* sizes a shop saws:
      the visible opening plus a ``groove`` tongue at each end, since the rail
      cope and the floating panel seat into the frame groove.

    The whole point is the relationship ``cut = visible + 2*groove`` lives in
    exactly one place; change a stile/rail/groove constant and both views move
    together.
    """

    opening_w: float
    opening_h: float
    rail_length: float
    panel_w: float
    panel_h: float


class CarcassDims(NamedTuple):
    """Canonical carcass part dimensions for a cabinet, in mm.

    The 3D geometry compiler (:mod:`geometry`) and the cut list (:mod:`cutlist`)
    both size the carcass from *these* numbers rather than each re-deriving them
    from the spec, so the model the Critic measures and the parts a shop saws
    cannot drift. Each consumer still arranges them into its own frame — the
    compiler into 3D extents plus positions, the cut list into
    length/width/thickness — but the *formulas* (the shelf clearances, the
    captured-vs-applied back) live here in exactly one place.
    """

    width: float            # overall carcass width
    depth: float            # carcass depth (the gable's width)
    box_height: float       # height of the box that sits above the toe kick
    carcass: float          # carcass-panel thickness
    interior_width: float   # clear width between the gables
    interior_depth: float   # clear depth in front of the back
    shelf_width: float      # adjustable-shelf width (interior − pin clearance)
    shelf_depth: float      # adjustable-shelf depth (interior − front setback)
    shelf_thickness: float
    back_thickness: float
    back_w: float           # back-panel horizontal extent
    back_h: float           # back-panel vertical extent
    toe_height: float


def carcass_dims(spec) -> CarcassDims:
    """Canonical carcass dimensions for a cabinet *spec* (see :class:`CarcassDims`).

    A captured back (rabbeted / grooved) is housed between the gables, so it is
    the interior width and stops a carcass thickness short of the full box
    height; an applied back lays over the rear edges at full width and height.
    """
    m = spec.material
    interior_w = spec.interior_width
    interior_d = spec.interior_depth
    box_h = spec.box_height
    applied = spec.back == BackStyle.APPLIED
    return CarcassDims(
        width=spec.width,
        depth=spec.depth,
        box_height=box_h,
        carcass=m.carcass,
        interior_width=interior_w,
        interior_depth=interior_d,
        shelf_width=interior_w - 2 * SHELF_SIDE_CLEARANCE,
        shelf_depth=interior_d - SHELF_SETBACK,
        shelf_thickness=m.shelf,
        back_thickness=m.back,
        back_w=spec.width if applied else interior_w,
        back_h=box_h if applied else box_h - m.carcass,
        toe_height=spec.toe_kick_height,
    )


def door_panel_dims(width: float, height: float, *,
                    stile: float = DOOR_STILE_WIDTH,
                    rail: float = DOOR_RAIL_WIDTH,
                    groove: float = DOOR_PANEL_GROOVE) -> DoorPanelDims:
    """Geometry of a 5-piece door leaf of overall ``width`` x ``height`` (mm).

    Callers apply their own degenerate-size floor (the cut list clamps to 50mm,
    the model to 10mm); this returns the raw arithmetic so that floor stays a
    caller concern and the shared formula stays here.
    """
    opening_w = width - 2 * stile
    opening_h = height - 2 * rail
    return DoorPanelDims(
        opening_w=opening_w,
        opening_h=opening_h,
        rail_length=opening_w + 2 * groove,
        panel_w=opening_w + 2 * groove,
        panel_h=opening_h + 2 * groove,
    )
