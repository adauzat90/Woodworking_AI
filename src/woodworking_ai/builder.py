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

from .dsl import CabinetSpec, ComponentGroup
from .geometry import panel_layout, project_layout, explode_panels


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


def _compound_from_panels(panels, label: str) -> Any:
    b3d = _require_build123d()
    Box, Pos, Compound, Rot = b3d.Box, b3d.Pos, b3d.Compound, b3d.Rot
    solids: list[Any] = []
    for p in panels:
        solid = Box(*p.size)
        if p.is_rotated:
            solid = Rot(0, 0, p.rot_z) * solid
        solid = Pos(*p.center) * solid
        solid.label = p.label
        solids.append(solid)
    model = Compound(children=solids)
    model.label = label
    return model


def build_model(spec: CabinetSpec, *, factor: float = 0.0,
                include: set | None = None) -> Any:
    """Return a build123d ``Compound`` of labelled panels for *spec*.

    Panel placement comes from :func:`woodworking_ai.geometry.panel_layout`, the
    same source the Critic agent measures against. Accepts a
    :class:`ComponentGroup` (Project or sub-assembly) too.

    ``factor`` > 0 returns an *exploded* model (sub-assemblies separated to show
    how it goes together); ``include`` keeps only the named sub-assemblies (for a
    progressive build view). With both defaults this is the assembled model.
    """
    if isinstance(spec, ComponentGroup):
        return build_project(spec, factor=factor, include=include)
    panels = (explode_panels(spec, factor, include)
              if (factor or include is not None) else panel_layout(spec))
    return _compound_from_panels(panels, spec.name)


def build_project(project: ComponentGroup, *, factor: float = 0.0,
                  include: set | None = None) -> Any:
    """Assemble a whole group into one build123d ``Compound`` (a run sections by
    cabinet). Supports the same ``factor``/``include`` explode/reveal options."""
    panels = (explode_panels(project, factor, include)
              if (factor or include is not None) else project_layout(project))
    return _compound_from_panels(panels, project.name)


def measure(model: Any) -> dict[str, float]:
    """Return the model's overall bounding-box dimensions (for the critic)."""
    bb = model.bounding_box()
    return {
        "width": bb.size.X,
        "depth": bb.size.Y,
        "height": bb.size.Z,
        "part_count": len(model.children),
    }
