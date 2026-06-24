"""Single source of truth for panel placement.

Both the geometry compiler (:mod:`builder`) and the Critic agent
(:mod:`agents.critic`) consume :func:`panel_layout`, so the 3D model and the
analytical checks can never drift apart. A :class:`PanelBox` is an axis-aligned
box in the shared frame:

    X = width  (left  -> right, 0 at center)
    Y = depth  (front -> back, 0 at the carcass front face)
    Z = height (floor -> up, 0 at the floor)
"""

from __future__ import annotations

from dataclasses import dataclass

from .dsl import CabinetSpec, BackStyle

# Construction constants shared with the cut list.
from .cutlist import STRETCHER_WIDTH, SHELF_SIDE_CLEARANCE, SHELF_SETBACK


@dataclass
class PanelBox:
    """One placed panel. ``size`` and ``center`` are (x, y, z) triples."""

    label: str
    size: tuple[float, float, float]
    center: tuple[float, float, float]
    category: str = "carcass"   # carcass | back | shelf | toe | front

    @property
    def is_front(self) -> bool:
        return self.category == "front"

    def bounds(self) -> tuple[tuple[float, float], ...]:
        """Return ((xmin, xmax), (ymin, ymax), (zmin, zmax))."""
        return tuple(
            (c - s / 2, c + s / 2) for c, s in zip(self.center, self.size)
        )


def panel_layout(spec: CabinetSpec) -> list[PanelBox]:
    """Return every panel of *spec* placed in the shared coordinate frame."""
    m = spec.material
    toe_h = spec.toe_kick.height if spec.toe_kick else 0.0
    box_h = spec.height - toe_h
    interior_w = spec.width - 2 * m.carcass
    interior_d = spec.depth - m.back
    # A captured back sits inside the carcass, so the rear rail is set forward of
    # it; an applied back lays on the outside rear face and needs no inset.
    back_inset = 0.0 if spec.back == BackStyle.APPLIED else m.back

    panels: list[PanelBox] = []

    def add(label, size, center, category="carcass"):
        panels.append(PanelBox(label, size, center, category))

    z_box = toe_h + box_h / 2
    y_center = spec.depth / 2

    # --- sides -----------------------------------------------------------
    x_side = spec.width / 2 - m.carcass / 2
    add("Side L", (m.carcass, spec.depth, box_h), (-x_side, y_center, z_box))
    add("Side R", (m.carcass, spec.depth, box_h), (x_side, y_center, z_box))

    # --- bottom ----------------------------------------------------------
    add("Bottom", (interior_w, interior_d, m.carcass),
        (0, interior_d / 2, toe_h + m.carcass / 2))

    # --- top stretchers (front + back) -----------------------------------
    z_top = toe_h + box_h - m.carcass / 2
    add("Stretcher front", (interior_w, STRETCHER_WIDTH, m.carcass),
        (0, STRETCHER_WIDTH / 2, z_top))
    add("Stretcher back", (interior_w, STRETCHER_WIDTH, m.carcass),
        (0, spec.depth - back_inset - STRETCHER_WIDTH / 2, z_top))

    # --- back ------------------------------------------------------------
    if spec.back == BackStyle.APPLIED:
        # Lays on the rear face, adding its thickness behind the carcass.
        add("Back", (spec.width, m.back, box_h),
            (0, spec.depth + m.back / 2, z_box), category="back")
    else:  # captured between the sides, in front of the rear edge
        add("Back", (interior_w, m.back, box_h - m.carcass),
            (0, spec.depth - m.back / 2, z_box), category="back")

    # --- shelves (evenly distributed in the interior) --------------------
    if spec.shelves > 0:
        shelf_w = interior_w - 2 * SHELF_SIDE_CLEARANCE
        shelf_d = interior_d - SHELF_SETBACK
        usable = box_h - 2 * m.carcass
        for i in range(spec.shelves):
            frac = (i + 1) / (spec.shelves + 1)
            z = toe_h + m.carcass + frac * usable
            add(f"Shelf {i + 1}", (shelf_w, shelf_d, m.shelf),
                (0, shelf_d / 2 + m.back, z), category="shelf")

    # --- toe kick --------------------------------------------------------
    if spec.toe_kick and toe_h > 0:
        setback = spec.toe_kick.setback
        add("Toe kick", (spec.width, m.carcass, toe_h),
            (0, setback + m.carcass / 2, toe_h / 2), category="toe")

    # --- fronts: drawers stack at the top, doors fill the rest -----------
    y_front = -m.door / 2
    drawer_band = 0.0
    z_cursor = toe_h + box_h
    for i, dr in enumerate(spec.drawers, start=1):
        fw = spec.width - 2 * spec.reveal
        z = z_cursor - spec.reveal - dr.front_height / 2
        add(f"Drawer front {i}", (fw, m.door, dr.front_height),
            (0, y_front, z), category="front")
        z_cursor -= dr.front_height + spec.reveal
        drawer_band += dr.front_height + spec.reveal

    door_region = box_h - drawer_band
    if spec.doors > 0 and door_region > 0:
        door_h = door_region - 2 * spec.reveal
        z = toe_h + (box_h - drawer_band) / 2
        if spec.doors == 1:
            dw = spec.width - 2 * spec.reveal
            add("Door", (dw, m.door, door_h), (0, y_front, z), category="front")
        else:
            dw = (spec.width - 3 * spec.reveal) / 2
            offset = spec.reveal / 2 + dw / 2
            add("Door L", (dw, m.door, door_h), (-offset, y_front, z), category="front")
            add("Door R", (dw, m.door, door_h), (offset, y_front, z), category="front")

    return panels
