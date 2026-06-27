"""Guard the shared carcass-dimension math.

The 3D geometry compiler (:func:`panel_layout`) and the cut list
(:func:`generate_cutlist`) must size every carcass part through the one
:func:`partmath.carcass_dims` helper, so the model the Critic measures and the
parts a shop saws cannot drift — the same class of bug that once made a door
panel 20 mm smaller in the model than on the cut list.

These tests assert that, for a representative spread of cabinets, each carcass
panel's 3D extents and its cut-list part are two views of the *same* numbers.
"""

import pytest

from woodworking_ai import CabinetSpec, Drawer, generate_cutlist
from woodworking_ai.dsl import BackStyle
from woodworking_ai.geometry import panel_layout
from woodworking_ai.partmath import carcass_dims
from woodworking_ai.constants import SHELF_SIDE_CLEARANCE, SHELF_SETBACK


def _cab(**kw):
    base = dict(width=900, height=720, depth=560, doors=2, shelves=1)
    base.update(kw)
    return CabinetSpec(**base)


# A spread that exercises every branch the helper folds in: base vs wall (full
# top), captured vs applied back, with/without shelves, drawers, face frame.
CASES = [
    _cab(),
    _cab(cabinet_type="wall", height=760, toe_kick=None),
    _cab(cabinet_type="tall", height=2100, shelves=4),
    _cab(back="applied"),
    _cab(shelves=0),
    _cab(construction="face_frame"),
    _cab(doors=0, drawers=[Drawer(160), Drawer(160), Drawer(200)]),
    _cab(width=450, depth=300),
]


def _panel(spec, label):
    return next(p for p in panel_layout(spec) if p.label == label)


def _part(spec, name):
    return next(p for p in generate_cutlist(spec).parts if p.name == name)


def _sorted_face(size_xyz):
    """The two larger extents of a panel — its sawn length & width, longest first."""
    a, b, c = sorted(size_xyz, reverse=True)
    return a, b  # drop the thickness (smallest extent)


@pytest.mark.parametrize("spec", CASES)
def test_carcass_dims_is_the_single_source(spec):
    """Both consumers must read identical numbers from the helper."""
    dims = carcass_dims(spec)
    assert dims.shelf_width == spec.interior_width - 2 * SHELF_SIDE_CLEARANCE
    assert dims.shelf_depth == spec.interior_depth - SHELF_SETBACK
    if spec.back == BackStyle.APPLIED:
        assert (dims.back_w, dims.back_h) == (spec.width, spec.box_height)
    else:
        assert (dims.back_w, dims.back_h) == (
            spec.interior_width, spec.box_height - spec.material.carcass)


@pytest.mark.parametrize("spec", CASES)
def test_side_panel_matches_cut_list(spec):
    panel = _panel(spec, "Side L")
    part = _part(spec, "Side")
    assert _sorted_face(panel.size) == (part.length, part.width)
    assert min(panel.size) == part.thickness


@pytest.mark.parametrize("spec", CASES)
def test_back_panel_matches_cut_list(spec):
    panel = _panel(spec, "Back")
    part = _part(spec, "Back")
    # The cut list sorts the back's face into length >= width; the model uses
    # raw extents. Compare the sorted faces so orientation isn't the variable.
    assert _sorted_face(panel.size) == (part.length, part.width)
    assert min(panel.size) == part.thickness


@pytest.mark.parametrize("spec", [c for c in CASES if c.shelves > 0])
def test_shelf_panel_matches_cut_list(spec):
    panel = _panel(spec, "Shelf 1")
    part = _part(spec, "Adjustable shelf")
    assert _sorted_face(panel.size) == (part.length, part.width)
    assert min(panel.size) == part.thickness


@pytest.mark.parametrize("spec", [c for c in CASES if c.toe_kick_height > 0])
def test_toe_kick_matches_cut_list(spec):
    panel = _panel(spec, "Toe kick")
    part = _part(spec, "Toe kick")
    assert _sorted_face(panel.size) == (part.length, part.width)
    assert min(panel.size) == part.thickness
