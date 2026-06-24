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

from .dsl import CabinetSpec
from .geometry import PanelBox, panel_layout

# Wood-ish palette by panel role.
CATEGORY_COLORS = {
    "carcass": "#caa472",
    "back": "#e6d2ad",
    "shelf": "#d8b98a",
    "toe": "#6b4f3a",
    "front": "#9c6b43",
}
CATEGORY_ALPHA = {"front": 0.92}


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
    (x0, x1), (y0, y1), (z0, z1) = p.bounds()
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
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

    ax.set_xlim(-spec.width / 2 - 20, spec.width / 2 + 20)
    ax.set_ylim(-spec.material.door - 20, spec.depth + 20)
    ax.set_zlim(0, spec.height + 20)
    try:
        ax.set_box_aspect((spec.width, spec.depth, spec.height))
    except Exception:  # older matplotlib
        pass
    ax.view_init(elev=22, azim=-58)
    ax.set_title("isometric", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])


def render_cabinet(spec: CabinetSpec, path: str | Path, *, dpi: int = 110) -> Path:
    """Render *spec* to a multi-view PNG at *path*; returns the path."""
    plt = _require_mpl()
    panels = panel_layout(spec)
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

    fig.suptitle(
        f"{spec.name} — {spec.width:.0f} x {spec.height:.0f} x {spec.depth:.0f} mm "
        f"({spec.construction.value}, {spec.doors} door / {len(spec.drawers)} drawer)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
