"""Shared construction constants (mm).

Centralised here so both the geometry compiler (:mod:`geometry`) and the cut
list (:mod:`cutlist`) read identical values without either module depending on
the other. Easy to tune in one place.
"""

from __future__ import annotations

SHELF_SIDE_CLEARANCE = 2.0     # gap each side so an adjustable shelf drops in
SHELF_SETBACK = 20.0           # shelf shallower than interior depth
STRETCHER_WIDTH = 80.0         # front/back top rails on a base cabinet
FRAME_WIDTH = 38.0             # face-frame stile/rail width (solid hardwood)
FRAME_THICKNESS = 19.0         # face-frame stock thickness
MULLION_WIDTH = 60.0           # frameless center post between a pair of doors
SLIDE_SIDE_CLEARANCE = 12.7    # gap each side for side-mount slides (½in nominal)
DRAWER_BOX_HEIGHT_DROP = 40.0  # box height below the drawer front
DRAWER_BOX_DEPTH_GAP = 25.0    # box shallower than the interior
MIN_DRAWER_BOX_HEIGHT = 60.0   # a box is never shorter than this
MIN_DRAWER_BOX_DEPTH = 100.0   # a box is never shallower than this
MIN_DRAWER_BOX_WIDTH_3D = 80.0 # 3D-model floor for a usable box width

# Five-piece (stile-and-rail) door construction.
DOOR_STILE_WIDTH = 57.0        # vertical stile width (~2-1/4in)
DOOR_RAIL_WIDTH = 57.0         # horizontal rail width
DOOR_PANEL_GROOVE = 10.0       # panel tongue captured this deep in the frame

# Housed joints (dado / groove / rabbet) — shared by joinery + geometry.
HOUSED_DEPTH_FRACTION = 0.5    # dado/groove depth as a fraction of stock
GROOVE_BACK_INSET = 12.0       # a grooved back sits this far in from the rear

# 32 mm "System 32" cabinetry grid: shelf-pin pitch, hinge-plate screws, and the
# line-boring grid all share this pitch. One definition for hardware / drilling /
# validator (they previously each declared their own copy).
SYSTEM_PITCH = 32.0

# 35 mm concealed (Euro) hinge cup geometry — shared by hardware / drilling /
# validator (previously triplicated under divergent names).
HINGE_CUP_DIA = 35.0
HINGE_CUP_DEPTH = 12.5
HINGE_CUP_INSET = 22.5         # cup centre in from the door's hinge edge

# Solid-wood glue-ups: panels wider than this are edge-glued from boards.
GLUE_UP_BOARD_WIDTH = 140.0    # nominal board width (~5-1/2in) before jointing
