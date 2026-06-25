"""Guard the shared drawer-box dimension math: the cut list and the 3D
geometry must size a drawer box through the one ``partmath.drawer_box_dims``
helper, so the model the Critic measures and the parts a shop cuts can't drift.
"""

from woodworking_ai import CabinetSpec, Drawer, generate_cutlist
from woodworking_ai.geometry import panel_layout
from woodworking_ai.partmath import drawer_box_dims
from woodworking_ai.constants import SLIDE_SIDE_CLEARANCE, MIN_DRAWER_BOX_WIDTH_3D


def _spec():
    return CabinetSpec(name="DB", width=600, height=720, depth=560, doors=0,
                       drawers=[Drawer(160)])


def test_drawer_box_dims_formula():
    w, h, d = drawer_box_dims(600, 160, 540)
    assert w == 600 - 2 * SLIDE_SIDE_CLEARANCE     # no floor by default
    w2, _, _ = drawer_box_dims(100, 160, 540, width_floor=MIN_DRAWER_BOX_WIDTH_3D)
    assert w2 == MIN_DRAWER_BOX_WIDTH_3D           # floor applied for the 3D model


def test_cutlist_box_width_comes_from_the_helper():
    spec = _spec()
    bottom = next(p for p in generate_cutlist(spec).parts
                  if p.name == "Drawer 1 box bottom")
    # The box bottom length is exactly the helper's width for the carcass
    # opening — i.e. the cut list no longer derives it independently.
    assert bottom.length == drawer_box_dims(spec.width, 160, spec.interior_depth)[0]


def test_geometry_emits_the_box_panels():
    panels = {p.label for p in panel_layout(_spec())}
    assert {"Drawer 1 box side L", "Drawer 1 box side R",
            "Drawer 1 box bottom"} <= panels
