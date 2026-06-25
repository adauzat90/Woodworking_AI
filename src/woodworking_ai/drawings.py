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
from .drilling import drilling_schedule, place_holes
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
    """A projected panel rectangle in one view (mm), plus its label/category.

    ``bores`` are the panel's drilled holes projected into this view as
    ``(h, v, dia)`` mm centres — populated only where the projection is
    unambiguous (door hinge cups on the front elevation), so a shop drawing
    shows the holes a CNC will bore.
    """
    h0: float
    v0: float
    h1: float
    v1: float
    label: str
    category: str
    part_id: str
    bores: list[tuple[float, float, float]] = None  # (h, v, dia)


def _door_bores_front(panel, h0: float, v0: float, holes_for
                      ) -> list[tuple[float, float, float]]:
    """Project a door's hinge-cup bores into the front elevation.

    A door's bores are local to its face — ``u`` across the width, ``v`` up from
    the bottom — which is exactly the front view's (h, v). We reuse the shared
    :func:`place_holes` transform (width along the view's h-axis) so the math
    matches the nest DXF. Only doors are handled; other parts' faces don't show
    their bores in these three orthographic views, so they are left empty.
    """
    holes, plen, pwid = holes_for(panel.label)
    if not holes:
        return []
    placed = place_holes(holes, plen, pwid, h0, v0,
                         rect_l=pwid, rect_w=plen)   # width -> h, length -> v
    return [(cx, cy, h.dia) for (cx, cy, h) in placed]


def _project(panels, h_ax: int, v_ax: int, label_for,
             bores_for=None) -> tuple[list[_Box], tuple]:
    boxes: list[_Box] = []
    hs: list[float] = []
    vs: list[float] = []
    front_view = (h_ax, v_ax) == (0, 2)
    for p in panels:
        (xb, yb, zb) = p.bounds()
        axes = (xb, yb, zb)
        h0, h1 = axes[h_ax]
        v0, v1 = axes[v_ax]
        hs += [h0, h1]
        vs += [v0, v1]
        bores: list[tuple[float, float, float]] = []
        if (front_view and bores_for is not None
                and p.category == "front" and p.label.startswith("Door")):
            bores = _door_bores_front(p, h0, v0, bores_for)
        boxes.append(_Box(h0, v0, h1, v1, p.label, p.category,
                          label_for(p.label), bores))
    bounds = (min(hs), max(hs), min(vs), max(vs)) if hs else (0, 0, 0, 0)
    return boxes, bounds


def _bores_lookup(spec, cl):
    """Return ``holes_for(label) -> (holes, part_length, part_width)``.

    Resolves a panel label to its drilling ops (matched by ``op.part``) and the
    door part's flat dimensions, so the projection knows the part's outline.
    """
    sched = drilling_schedule(spec)
    by_part: dict[str, list] = {}
    for op in sched.ops:
        by_part.setdefault(op.part, []).extend(op.holes)
    door = next((p for p in cl.parts if p.name == "Door"), None)

    def holes_for(label: str):
        if door is None or not label.startswith("Door"):
            return [], 0.0, 0.0
        return by_part.get(label, []), door.length, door.width

    return holes_for


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
        for (bh_, bv_, dia) in (b.bores or ()):
            out.append(f'<circle cx="{sx(bh_):.1f}" cy="{sy(bv_):.1f}" '
                       f'r="{dia / 2 * scale:.1f}" class="bore"/>')

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
.bore{fill:none;stroke:#9c6b43;stroke-width:0.7}
"""


def render_svg(spec, unit: str = "metric") -> str:
    """Return one SVG string with front / side / plan dimensioned views."""
    panels = panel_layout(spec)
    cl = generate_cutlist(spec)
    label_for = cl.part_id_for_label
    bores_for = _bores_lookup(spec, cl)

    projected = [(_project(panels, h, v, label_for, bores_for), name, h, v)
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
    bores_for = _bores_lookup(spec, cl)

    def nominal(axis: int, lo: float, hi: float) -> float:
        attr = ("width", "depth", "height")[axis]
        val = getattr(spec, attr, None)
        return float(val) if isinstance(val, (int, float)) else (hi - lo)

    out = []
    for (name, h, v) in _VIEWS:
        boxes, bounds = _project(panels, h, v, label_for, bores_for)
        label_dims = (nominal(h, bounds[0], bounds[1]),
                      nominal(v, bounds[2], bounds[3]))
        out.append((name, h, v, boxes, bounds, label_dims))
    return out
