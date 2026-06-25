"""Guard the tech-debt constant unification: the values that used to be
duplicated (and one that conflicted) now have exactly one definition in
``constants.py``, and every former copy is an identity alias of it. If someone
re-introduces a local literal, these assertions fail.
"""

from woodworking_ai import constants as C
from woodworking_ai import hardware, drilling
from woodworking_ai.validator import (
    SIDE_MOUNT_CLEARANCE, SYSTEM_PITCH as V_PITCH,
    HINGE_CUP_DIA as V_DIA, HINGE_CUP_INSET as V_INSET,
)
from woodworking_ai.dsl import Drawer


def test_slide_clearance_single_source_and_reconciled():
    # The old conflict: constants said 13.0, everyone else 12.7. Now one value.
    assert C.SLIDE_SIDE_CLEARANCE == 12.7
    assert SIDE_MOUNT_CLEARANCE == C.SLIDE_SIDE_CLEARANCE
    assert hardware.SlideSpec.side_clearance == C.SLIDE_SIDE_CLEARANCE
    assert Drawer().slide_clearance == C.SLIDE_SIDE_CLEARANCE


def test_system_pitch_single_source():
    assert C.SYSTEM_PITCH == 32.0
    assert hardware.PLATE_SCREW_PITCH == C.SYSTEM_PITCH
    assert drilling.SYSTEM_PITCH == C.SYSTEM_PITCH
    assert V_PITCH == C.SYSTEM_PITCH


def test_hinge_cup_single_source():
    assert (hardware.CUP_DIA, hardware.CUP_DEPTH, hardware.CUP_INSET) == (
        C.HINGE_CUP_DIA, C.HINGE_CUP_DEPTH, C.HINGE_CUP_INSET)
    assert (drilling.HINGE_CUP_DIA, drilling.HINGE_CUP_DEPTH,
            drilling.HINGE_CUP_INSET) == (
        C.HINGE_CUP_DIA, C.HINGE_CUP_DEPTH, C.HINGE_CUP_INSET)
    assert (V_DIA, V_INSET) == (C.HINGE_CUP_DIA, C.HINGE_CUP_INSET)
