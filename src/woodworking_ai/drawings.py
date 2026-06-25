"""Dimensioned 2D shop drawings (SVG, no CAD dependency).

A GLB is nice on screen, but a shop builds from *dimensioned orthographic
drawings*. This module projects the shared :func:`panel_layout` onto three
standard views — front elevation, side, and plan — and emits one self-contained
SVG with the overall dimensions and part-ID callouts on the front faces. SVG is
plain text: it prints cleanly, scales without loss, and embeds straight into the
HTML/PDF build package.

Coordinate frame (shared with :mod:`geometry`): X = width, Y = depth, Z = up.
Each view picks a horizontal and vertical axis; SVG's y grows downward, so the
vertical axis is flipped on output (up is up).
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import panel_layout
from .cutlist import generate_cutlist
from .units import format_length

# Axis index per view: (horizontal_axis, vertical_axis) into (x, y, z).
_VIEWS = (("Front elevation", 0, 2), ("Side", 1, 2), ("Plan", 0, 1))
_TARGET = 240.0     # px for the largest single view dimension
_MARGIN = 54.0      # px around each view for dimension lines + labels
_GAP = 40.0         # px between views


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


@dataclass
class _Box:
    """A projected panel rectangle in one view (mm), plus its label/category."""
    h0: float
    v0: float
    h1: float
    v1: float
    label: str
    category: str
    part_id: str


def _project(panels, h_ax: int, v_ax: int, label_for) -> tuple[list[_Box], tuple]:
    boxes: list[_Box] = []
    hs: list[float] = []
    vs: list[float] = []
    for p in panels:
        (xb, yb, zb) = p.bounds()
        axes = (xb, yb, zb)
        h0, h1 = axes[h_ax]
        v0, v1 = axes[v_ax]
        hs += [h0, h1]
        vs += [v0, v1]
        boxes.append(_Box(h0, v0, h1, v1, p.label, p.category,
                          label_for(p.label)))
    bounds = (min(hs), max(hs), min(vs), max(vs)) if hs else (0, 0, 0, 0)
    return boxes, bounds


def _svg_view(title: str, boxes: list[_Box], bounds: tuple, scale: float,
              ox: float, oy: float, unit: str,
              label_dims: tuple[float, float]) -> tuple[list[str], float, float]:
    """Render one view as SVG fragments; return (parts, width_px, height_px).

    Geometry uses the projected *bounds* (the true envelope); the overall
    dimension *labels* use ``label_dims`` — the nominal width/height/depth a
    shop expects, rather than an envelope inflated by a proud overlay front.
    """
    hmin, hmax, vmin, vmax = bounds
    w_mm, h_mm = (hmax - hmin), (vmax - vmin)
    w_px, h_px = w_mm * scale, h_mm * scale
    label_w, label_h = label_dims

    def sx(h: float) -> float:
        return ox + _MARGIN + (h - hmin) * scale

    def sy(v: float) -> float:                 # flip so 'up' is up
        return oy + _MARGIN + (vmax - v) * scale

    out: list[str] = [
        f'<text x="{ox + _MARGIN:.1f}" y="{oy + 16:.1f}" class="title">'
        f'{_esc(title)}</text>']

    # Front-category panels filled + labelled; everything else as a light outline.
    for b in sorted(boxes, key=lambda b: b.category != "front"):
        x, y = sx(b.h0), sy(b.v1)
        bw, bh = (b.h1 - b.h0) * scale, (b.v1 - b.v0) * scale
        cls = "front" if b.category == "front" else "panel"
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                   f'height="{bh:.1f}" class="{cls}"/>')
        if b.category == "front" and bw > 18 and bh > 12:
            tag = b.part_id or ""
            out.append(f'<text x="{x + bw / 2:.1f}" y="{y + bh / 2 + 3:.1f}" '
                       f'class="lbl">{_esc(tag)}</text>')

    # Overall dimensions: width along the bottom, height up the left side.
    by = oy + _MARGIN + h_px + 16
    out += _dim_h(sx(hmin), sx(hmax), by, format_length(label_w, unit, mark=True))
    lx = ox + _MARGIN - 16
    out += _dim_v(sy(vmin), sy(vmax), lx, format_length(label_h, unit, mark=True))
    return out, w_px + 2 * _MARGIN, h_px + 2 * _MARGIN


def _dim_h(x1: float, x2: float, y: float, label: str) -> list[str]:
    return [
        f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" class="dim"/>',
        f'<line x1="{x1:.1f}" y1="{y - 4:.1f}" x2="{x1:.1f}" y2="{y + 4:.1f}" class="dim"/>',
        f'<line x1="{x2:.1f}" y1="{y - 4:.1f}" x2="{x2:.1f}" y2="{y + 4:.1f}" class="dim"/>',
        f'<text x="{(x1 + x2) / 2:.1f}" y="{y + 14:.1f}" class="dimtext">{_esc(label)}</text>']


def _dim_v(y1: float, y2: float, x: float, label: str) -> list[str]:
    ya, yb = min(y1, y2), max(y1, y2)
    return [
        f'<line x1="{x:.1f}" y1="{ya:.1f}" x2="{x:.1f}" y2="{yb:.1f}" class="dim"/>',
        f'<line x1="{x - 4:.1f}" y1="{ya:.1f}" x2="{x + 4:.1f}" y2="{ya:.1f}" class="dim"/>',
        f'<line x1="{x - 4:.1f}" y1="{yb:.1f}" x2="{x + 4:.1f}" y2="{yb:.1f}" class="dim"/>',
        f'<text x="{x - 8:.1f}" y="{(ya + yb) / 2:.1f}" class="dimtext" '
        f'transform="rotate(-90 {x - 8:.1f} {(ya + yb) / 2:.1f})">{_esc(label)}</text>']


_STYLE = """
.title{font:600 12px system-ui,sans-serif;fill:#3a352f}
.panel{fill:none;stroke:#b9b0a2;stroke-width:0.8}
.front{fill:#e7d8bf;stroke:#9c6b43;stroke-width:1}
.lbl{font:600 10px system-ui,sans-serif;fill:#5a4632;text-anchor:middle}
.dim{stroke:#6b8aa5;stroke-width:0.7}
.dimtext{font:10px system-ui,sans-serif;fill:#3f5468;text-anchor:middle}
"""


def render_svg(spec, unit: str = "metric") -> str:
    """Return one SVG string with front / side / plan dimensioned views."""
    panels = panel_layout(spec)
    cl = generate_cutlist(spec)
    label_for = cl.part_id_for_label

    projected = [(_project(panels, h, v, label_for), name, h, v)
                 for (name, h, v) in _VIEWS]
    # One shared scale so the three views read at the same size.
    extent = 1.0
    for ((_, bounds), _name, _h, _v) in projected:
        extent = max(extent, bounds[1] - bounds[0], bounds[3] - bounds[2])
    scale = _TARGET / extent

    # Nominal overall sizes per axis (X=width, Y=depth, Z=height), so the
    # dimension labels read as the cabinet's nominal size, not the AABB.
    def nominal(axis: int, bounds_lo: float, bounds_hi: float) -> float:
        attr = ("width", "depth", "height")[axis]
        val = getattr(spec, attr, None)
        return float(val) if isinstance(val, (int, float)) else (bounds_hi - bounds_lo)

    parts: list[str] = []
    ox = 0.0
    total_h = 0.0
    for ((boxes, bounds), name, h_ax, v_ax) in projected:
        label_dims = (nominal(h_ax, bounds[0], bounds[1]),
                      nominal(v_ax, bounds[2], bounds[3]))
        frag, w_px, h_px = _svg_view(name, boxes, bounds, scale, ox, 0.0, unit,
                                     label_dims)
        parts += frag
        ox += w_px + _GAP
        total_h = max(total_h, h_px)
    width = ox
    height = total_h + 24

    name = _esc(getattr(spec, "name", "Design"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">'
        f'<style>{_STYLE}</style>'
        f'<rect width="{width:.0f}" height="{height:.0f}" fill="#fbf8f3"/>'
        + "".join(parts)
        + f'<text x="6" y="{height - 6:.1f}" class="dimtext" '
          f'style="text-anchor:start">{name} — not to scale</text>'
        + '</svg>')


def write_drawings_svg(spec, path, unit: str = "metric"):
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_svg(spec, unit), encoding="utf-8")
    return path


def projected_views(spec):
    """View data for other renderers (e.g. the PDF build package).

    Returns a list of ``(name, h_axis, v_axis, boxes, bounds, label_dims)`` —
    the same projection the SVG uses, so any renderer draws identical views.
    """
    panels = panel_layout(spec)
    cl = generate_cutlist(spec)
    label_for = cl.part_id_for_label

    def nominal(axis: int, lo: float, hi: float) -> float:
        attr = ("width", "depth", "height")[axis]
        val = getattr(spec, attr, None)
        return float(val) if isinstance(val, (int, float)) else (hi - lo)

    out = []
    for (name, h, v) in _VIEWS:
        boxes, bounds = _project(panels, h, v, label_for)
        label_dims = (nominal(h, bounds[0], bounds[1]),
                      nominal(v, bounds[2], bounds[3]))
        out.append((name, h, v, boxes, bounds, label_dims))
    return out
