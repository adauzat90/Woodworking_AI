"""Shared construction constants (mm).

Centralised here so both the geometry compiler (:mod:`geometry`) and the cut
list (:mod:`cutlist`) read identical values without either module depending on
the other. Easy to tune in one place.
"""

from __future__ import annotations

SHELF_SIDE_CLEARANCE = 2.0     # gap each side so an adjustable shelf drops in
SHELF_SETBACK = 20.0           # shelf shallower than interior depth
STRETCHER_WIDTH = 80.0         # front/back top rails on a base cabinet
BACK_RABBET = 0.0              # rabbeted back recess captured via interior depth
FRAME_WIDTH = 38.0             # face-frame stile/rail width (solid hardwood)
FRAME_THICKNESS = 19.0         # face-frame stock thickness
MULLION_WIDTH = 60.0           # frameless center post between a pair of doors
SLIDE_SIDE_CLEARANCE = 13.0    # gap each side for ball-bearing slides
DRAWER_BOX_HEIGHT_DROP = 40.0  # box height below the drawer front
DRAWER_BOX_DEPTH_GAP = 25.0    # box shallower than the interior
