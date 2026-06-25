"""Shared part-dimension math.

One definition of the sizes that the geometry compiler (:mod:`geometry`) and the
cut list (:mod:`cutlist`) must agree on. Both modules used to derive these
numbers independently from the same constants, which let the 3D model and the
cut list drift apart. Keeping the arithmetic here means they cannot.

Pure arithmetic — no CAD dependency.
"""

from __future__ import annotations

from .constants import (
    SLIDE_SIDE_CLEARANCE, DRAWER_BOX_HEIGHT_DROP, DRAWER_BOX_DEPTH_GAP,
    MIN_DRAWER_BOX_HEIGHT, MIN_DRAWER_BOX_DEPTH,
)


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
