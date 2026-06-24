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

from .dsl import CabinetSpec
from .geometry import panel_layout


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
    """Return a build123d ``Compound`` of labelled panels for *spec*.

    Panel placement comes from :func:`woodworking_ai.geometry.panel_layout`, the
    same source the Critic agent measures against.
    """
    b3d = _require_build123d()
    Box, Pos, Compound, Rot = b3d.Box, b3d.Pos, b3d.Compound, b3d.Rot

    solids: list[Any] = []
    for p in panel_layout(spec):
        solid = Box(*p.size)
        if p.is_rotated:
            solid = Rot(0, 0, p.rot_z) * solid
        solid = Pos(*p.center) * solid
        solid.label = p.label
        solids.append(solid)

    model = Compound(children=solids)
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
