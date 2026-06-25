"""Headless rendering of a cabinet to images.

Draws the panels from :func:`panel_layout` — the same source the compiler and
Critic use — into a front elevation, a side elevation, and an isometric 3D view,
saved as a single PNG. Uses matplotlib's Agg backend, so it needs **no display,
no GPU, and no CAD kernel**. These snapshots are what the render-based Critic
hands to a vision model for review (the visual half of Zookeeper's approach).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dsl import CabinetSpec, ComponentGroup
from .geometry import PanelBox, panel_layout

# Wood-ish palette by panel role.
CATEGORY_COLORS = {
    "carcass": "#caa472",
    "back": "#e6d2ad",
    "shelf": "#d8b98a",
    "toe": "#6b4f3a",
    "frame": "#7a5230",
    "front": "#9c6b43",
    # applied trim / accessories
    "counter": "#3f3a36",
    "filler": "#8a6a47",
    "endpanel": "#9c6b43",
    "molding": "#7a5230",
}
CATEGORY_ALPHA = {"front": 0.92, "counter": 0.97}


def _require_mpl() -> Any:
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless
        import matplotlib.pyplot as plt
        return plt
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "matplotlib is required for rendering. Install it with:\n"
            "    pip install matplotlib"
        ) from exc


def _color(p: PanelBox) -> str:
    return CATEGORY_COLORS.get(p.category, "#bbbbbb")


def _elevation(ax, panels: list[PanelBox], haxis: int, vaxis: int,
               depth_axis: int, title: str) -> None:
    """Draw a flat elevation; panels farther along *depth_axis* are drawn first."""
    from matplotlib.patches import Rectangle

    for p in sorted(panels, key=lambda q: q.center[depth_axis], reverse=True):
        b = p.bounds()
        (h0, h1), (v0, v1) = b[haxis], b[vaxis]
        ax.add_patch(Rectangle(
            (h0, v0), h1 - h0, v1 - v0,
            facecolor=_color(p), edgecolor="#3a2a1a", linewidth=0.6,
            alpha=CATEGORY_ALPHA.get(p.category, 1.0),
        ))
    _fit(ax, panels, haxis, vaxis)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])


def _fit(ax, panels, haxis, vaxis, pad: float = 30.0) -> None:
    hs = [c for p in panels for c in p.bounds()[haxis]]
    vs = [c for p in panels for c in p.bounds()[vaxis]]
    ax.set_xlim(min(hs) - pad, max(hs) + pad)
    ax.set_ylim(min(vs) - pad, max(vs) + pad)


def _cuboid_faces(p: PanelBox):
    import math
    cx, cy, cz = p.center
    sx, sy, sz = p.size
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    a = math.radians(p.rot_z)
    ca, sa = math.cos(a), math.sin(a)

    def world(dx, dy, dz):
        # Rotate the local (dx, dy) about Z, then translate to the centre.
        return (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca, cz + dz)

    v = [
        world(-hx, -hy, -hz), world(hx, -hy, -hz), world(hx, hy, -hz), world(-hx, hy, -hz),
        world(-hx, -hy, hz), world(hx, -hy, hz), world(hx, hy, hz), world(-hx, hy, hz),
    ]
    idx = [
        (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
        (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4),
    ]
    return [[v[i] for i in face] for face in idx]


def _isometric(ax, panels: list[PanelBox], spec: CabinetSpec) -> None:
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    for p in panels:
        coll = Poly3DCollection(
            _cuboid_faces(p), facecolor=_color(p),
            edgecolor="#3a2a1a", linewidths=0.3,
            alpha=CATEGORY_ALPHA.get(p.category, 1.0),
        )
        ax.add_collection3d(coll)

    # Limits from the actual panel extents, so this works for any furniture.
    xs = [c for p in panels for c in p.bounds()[0]]
    ys = [c for p in panels for c in p.bounds()[1]]
    zs = [c for p in panels for c in p.bounds()[2]]
    ax.set_xlim(min(xs) - 20, max(xs) + 20)
    ax.set_ylim(min(ys) - 20, max(ys) + 20)
    ax.set_zlim(min(zs), max(zs) + 20)
    try:
        ax.set_box_aspect((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
    except Exception:  # older matplotlib
        pass
    ax.view_init(elev=22, azim=-58)
    ax.set_title("isometric", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])


def _title(spec, panels: list[PanelBox]) -> str:
    """A one-line caption that works for a cabinet, a table, or a whole group."""
    if isinstance(spec, ComponentGroup):
        def span(axis):
            cs = [c for p in panels for c in p.bounds()[axis]]
            return (max(cs) - min(cs)) if cs else 0.0
        dims = f"{span(0):.0f} x {span(2):.0f} x {span(1):.0f} mm"
        return f"{spec.name} — {dims}  ({len(spec.components)} components)"
    dims = f"{spec.width:.0f} x {spec.height:.0f} x {spec.depth:.0f} mm"
    if hasattr(spec, "construction"):
        sub = f"{spec.construction.value}, {spec.doors} door / {len(spec.drawers)} drawer"
    else:
        sub = getattr(spec, "kind", "furniture")
    return f"{spec.name} — {dims}  ({sub})"


def render_cabinet(spec, path: str | Path, *, dpi: int = 110,
                   panels: list[PanelBox] | None = None) -> Path:
    """Render *spec* (cabinet, table, or project) to a multi-view PNG.

    Pass ``panels`` to draw a specific panel set (e.g. an exploded view from
    :func:`woodworking_ai.geometry.explode_panels`) instead of the assembled
    layout.
    """
    plt = _require_mpl()
    panels = panel_layout(spec) if panels is None else panels
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(12, 4.2))
    ax_front = fig.add_subplot(1, 3, 1)
    ax_side = fig.add_subplot(1, 3, 2)
    ax_iso = fig.add_subplot(1, 3, 3, projection="3d")

    # Front elevation: width (X) vs height (Z), depth = Y (front panels nearest).
    _elevation(ax_front, panels, haxis=0, vaxis=2, depth_axis=1, title="front")
    # Side elevation: depth (Y) vs height (Z), looking along X.
    _elevation(ax_side, panels, haxis=1, vaxis=2, depth_axis=0, title="side")
    _isometric(ax_iso, panels, spec)

    fig.suptitle(_title(spec, panels), fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
