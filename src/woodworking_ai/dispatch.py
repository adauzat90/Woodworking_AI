"""Single definition of the pipeline's spec-type dispatch.

Every stage — validator, cut list, estimator, drilling, joinery, geometry,
assembly steps, … — used to re-implement the *same* ``isinstance`` ladder to
decide what kind of spec it was handed:

    if isinstance(spec, ApplianceVoid): ...
    elif isinstance(spec, ComponentGroup): ...   # Project / Assembly
    elif isinstance(spec, TableSpec): ...
    else:  # a cabinet

That ladder is the codebase's biggest extensibility tax: adding a furniture
type meant finding and editing a dozen copies in lockstep. It now lives here,
so the type taxonomy is defined once and each stage dispatches on the result.

Pure data — no CAD dependency.
"""

from __future__ import annotations

from .dsl import (
    ApplianceVoid, ComponentGroup, TableSpec, WallShelfSpec, BoxSpec, BenchSpec,
    FrameSpec, BedSpec, CuttingBoardSpec,
)

# Canonical pipeline kinds. ``GROUP`` covers Project and Assembly (and any
# future ComponentGroup subclass); ``CABINET`` is the default leaf. Each leaf
# kind has a registered implementation in :mod:`furniture`.
VOID = "void"
GROUP = "group"
TABLE = "table"
WALL_SHELF = "wall_shelf"
BOX = "box"
BENCH = "bench"
FRAME = "frame"
BED = "bed"
CUTTING_BOARD = "cutting_board"
CABINET = "cabinet"


def spec_kind(spec) -> str:
    """The pipeline category of *spec*.

    Order matters: an ``ApplianceVoid`` is a leaf placeholder, a
    ``ComponentGroup`` aggregates components, then the leaf furniture types in
    turn, and everything else is treated as a cabinet.
    """
    if isinstance(spec, ApplianceVoid):
        return VOID
    if isinstance(spec, ComponentGroup):
        return GROUP
    if isinstance(spec, TableSpec):
        return TABLE
    if isinstance(spec, WallShelfSpec):
        return WALL_SHELF
    if isinstance(spec, BoxSpec):
        return BOX
    if isinstance(spec, BenchSpec):
        return BENCH
    if isinstance(spec, FrameSpec):
        return FRAME
    if isinstance(spec, BedSpec):
        return BED
    if isinstance(spec, CuttingBoardSpec):
        return CUTTING_BOARD
    return CABINET


def is_group(spec) -> bool:
    """True for a Project/Assembly (any :class:`ComponentGroup`)."""
    return isinstance(spec, ComponentGroup)
