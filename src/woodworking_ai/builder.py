"""The compiler: a cabinet spec -> build123d B-Rep geometry.

This is where the parametric language becomes real 3D. We place each panel as a
box in a shared coordinate frame:

    X = width  (left  -> right)
    Y = depth  (front -> back)
    Z = height (floor -> up)

build123d (OpenCascade) is an optional, heavy dependency. The import is lazy so
the rest of the package (DSL, validator, cut list) works without it; geometry
functions raise a clear error if it is missing.
"""

from __future__ import annotations

from typing import Any

from .dsl import CabinetSpec, BackStyle
from .cutlist import STRETCHER_WIDTH


def _require_build123d() -> Any:
    try:
        import build123d as b3d  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "build123d is required for geometry/export. Install it with:\n"
            "    pip install build123d\n"
            "(The DSL, validator and cut list work without it.)"
        ) from exc
    return b3d


def build_model(spec: CabinetSpec) -> Any:
    """Return a build123d ``Compound`` of labelled panels for *spec*."""
    b3d = _require_build123d()
    Box, Pos, Compound = b3d.Box, b3d.Pos, b3d.Compound

    m = spec.material
    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    box_h = spec.height - toe_h
    interior_w = spec.width - 2 * m.carcass
    interior_d = spec.depth - m.back

    panels: list[Any] = []

    def panel(label: str, size: tuple[float, float, float],
              center: tuple[float, float, float]) -> None:
        solid = Pos(*center) * Box(*size)
        solid.label = label
        panels.append(solid)

    z_box = toe_h + box_h / 2          # vertical center of the carcass box
    y_center = spec.depth / 2          # front face at y=0, back at y=depth

    # --- sides -----------------------------------------------------------
    x_side = spec.width / 2 - m.carcass / 2
    panel("Side L", (m.carcass, spec.depth, box_h), (-x_side, y_center, z_box))
    panel("Side R", (m.carcass, spec.depth, box_h), (x_side, y_center, z_box))

    # --- bottom ----------------------------------------------------------
    panel("Bottom", (interior_w, interior_d, m.carcass),
          (0, interior_d / 2, toe_h + m.carcass / 2))

    # --- top stretchers (front + back) -----------------------------------
    z_top = toe_h + box_h - m.carcass / 2
    panel("Stretcher front", (interior_w, STRETCHER_WIDTH, m.carcass),
          (0, STRETCHER_WIDTH / 2, z_top))
    panel("Stretcher back", (interior_w, STRETCHER_WIDTH, m.carcass),
          (0, spec.depth - STRETCHER_WIDTH / 2, z_top))

    # --- back ------------------------------------------------------------
    if spec.back == BackStyle.APPLIED:
        panel("Back", (spec.width, m.back, box_h),
              (0, spec.depth - m.back / 2, z_box))
    else:  # captured between the sides
        panel("Back", (interior_w, m.back, box_h - m.carcass),
              (0, spec.depth - m.back / 2, z_box))

    # --- shelves (evenly distributed in the interior) --------------------
    if spec.shelves > 0:
        shelf_w = interior_w - 4.0
        shelf_d = interior_d - 20.0
        usable = box_h - 2 * m.carcass
        for i in range(spec.shelves):
            frac = (i + 1) / (spec.shelves + 1)
            z = toe_h + m.carcass + frac * usable
            panel(f"Shelf {i + 1}", (shelf_w, shelf_d, m.shelf),
                  (0, shelf_d / 2 + m.back, z))

    # --- toe kick --------------------------------------------------------
    if spec.toe_kick and toe_h > 0:
        setback = spec.toe_kick.setback
        panel("Toe kick", (spec.width, m.carcass, toe_h),
              (0, setback + m.carcass / 2, toe_h / 2))

    # --- fronts: drawers at the top, doors below -------------------------
    y_front = -m.door / 2  # door faces sit just proud of the carcass front
    drawer_band = 0.0
    z_cursor = toe_h + box_h  # start at the top, work down
    for i, dr in enumerate(spec.drawers, start=1):
        fw = spec.width - 2 * spec.reveal
        z = z_cursor - spec.reveal - dr.front_height / 2
        panel(f"Drawer front {i}", (fw, m.door, dr.front_height), (0, y_front, z))
        z_cursor -= dr.front_height + spec.reveal
        drawer_band += dr.front_height + spec.reveal

    door_region = box_h - drawer_band
    if spec.doors > 0 and door_region > 0:
        door_h = door_region - 2 * spec.reveal
        z = toe_h + (box_h - drawer_band) / 2
        if spec.doors == 1:
            dw = spec.width - 2 * spec.reveal
            panel("Door", (dw, m.door, door_h), (0, y_front, z))
        else:
            dw = (spec.width - 3 * spec.reveal) / 2
            offset = spec.reveal / 2 + dw / 2
            panel("Door L", (dw, m.door, door_h), (-offset, y_front, z))
            panel("Door R", (dw, m.door, door_h), (offset, y_front, z))

    model = Compound(children=panels)
    model.label = spec.name
    return model


def measure(model: Any) -> dict[str, float]:
    """Return the model's overall bounding-box dimensions (for the critic)."""
    bb = model.bounding_box()
    return {
        "width": bb.size.X,
        "depth": bb.size.Y,
        "height": bb.size.Z,
        "part_count": len(model.children),
    }
