"""Shared reportlab building blocks for the PDF documents.

:mod:`woodworking_ai.report` (the shop build package) and
:mod:`woodworking_ai.proposal` (the customer proposal) both draw the same
to-scale orthographic views, embed the same matplotlib render, and lay out
tables with the same brown/cream house style. Those near-identical reportlab
blocks live here once, parameterized by the few things that actually differ
between the two documents (fill colors and whether per-part IDs are printed).

Like the two callers, every reportlab import is deferred so the rest of the
package keeps running without the optional ``pdf`` extra installed.
"""

from __future__ import annotations

from .drawings import projected_views
from .units import format_length


# Color palettes for :func:`elevation_flowable`. The shop drawings
# (``report``) use a slightly darker, more saturated front; the customer
# proposal uses a lighter, cleaner outline and also tints the view-name label.
SHOP_COLORS = {
    "name_fill": None,  # report leaves the name in the inherited (black) color
    "front_stroke": (0.61, 0.42, 0.26),
    "front_fill": (0.91, 0.85, 0.75),
    "other_stroke": (0.73, 0.69, 0.64),
    "id_fill": (0.35, 0.27, 0.2),
    "dim_fill": (0.25, 0.33, 0.41),
}

PROPOSAL_COLORS = {
    "name_fill": (0.2, 0.2, 0.2),
    "front_stroke": (0.55, 0.4, 0.27),
    "front_fill": (0.93, 0.88, 0.80),
    "other_stroke": (0.7, 0.66, 0.6),
    "id_fill": None,
    "dim_fill": (0.25, 0.33, 0.41),
}


def elevation_flowable(spec, unit, avail_w, *, show_ids: bool, colors: dict):
    """A reportlab Flowable drawing the three orthographic views to scale.

    Shared by the shop build package and the customer proposal. The two differ
    only in the fill/stroke ``colors`` palette and whether per-part IDs are
    printed inside the front panels (``show_ids``); everything else — the scale
    math, the view loop, the overall dimension callouts — is identical.
    """
    from reportlab.platypus import Flowable

    views = projected_views(spec)
    margin = 30.0
    gap = 24.0
    raw_w = sum((b[1] - b[0]) for (_n, _h, _v, _bx, b, _ld) in views)
    n = len(views)
    scale = (avail_w - 2 * margin * n - gap * (n - 1)) / max(raw_w, 1.0)
    scale = max(min(scale, 0.25), 0.02)
    height = margin * 2 + max((b[3] - b[2]) for (*_, b, _ld) in views) * scale + 24

    class _Views(Flowable):
        def wrap(self, _w, _h):
            return (avail_w, height)

        def draw(self):
            c = self.canv
            ox = 0.0
            for (name, _h, _v, boxes, bounds, label_dims) in views:
                hmin, hmax, vmin, vmax = bounds
                w_mm, h_mm = hmax - hmin, vmax - vmin
                bx = ox + margin
                by = margin

                # Bind the per-view loop vars as defaults so these helpers can't
                # capture a later iteration's values (they're called in-loop, so
                # this is belt-and-suspenders, but it satisfies the closure check).
                def sx(hh, bx=bx, hmin=hmin):
                    return bx + (hh - hmin) * scale

                def sy(vv, by=by, vmin=vmin):
                    return by + (vv - vmin) * scale

                c.setFont("Helvetica-Bold", 8)
                if colors["name_fill"] is not None:
                    c.setFillColorRGB(*colors["name_fill"])
                c.drawString(bx, by + h_mm * scale + 8, name)
                for b in sorted(boxes, key=lambda b: b.category != "front"):
                    x, y = sx(b.h0), sy(b.v0)
                    bw, bh = (b.h1 - b.h0) * scale, (b.v1 - b.v0) * scale
                    if b.category == "front":
                        c.setStrokeColorRGB(*colors["front_stroke"])
                        c.setFillColorRGB(*colors["front_fill"])
                        c.rect(x, y, bw, bh, stroke=1, fill=1)
                        if show_ids and b.part_id and bw > 14 and bh > 10:
                            c.setFillColorRGB(*colors["id_fill"])
                            c.setFont("Helvetica-Bold", 6)
                            c.drawCentredString(x + bw / 2, y + bh / 2 - 2, b.part_id)
                    else:
                        c.setStrokeColorRGB(*colors["other_stroke"])
                        c.rect(x, y, bw, bh, stroke=1, fill=0)
                # Overall dimension labels (nominal sizes).
                c.setFillColorRGB(*colors["dim_fill"])
                c.setFont("Helvetica", 7)
                c.drawCentredString(bx + w_mm * scale / 2, by - 10,
                                    format_length(label_dims[0], unit, mark=True))
                c.drawString(bx + w_mm * scale + 4, by + h_mm * scale / 2,
                             format_length(label_dims[1], unit, mark=True))
                ox += margin * 2 + w_mm * scale + gap

    return _Views()


def model_image(spec, avail_w, *, exploded: bool = False):
    """A reportlab Image of the model (assembled or exploded), or ``None``.

    Rendered headlessly with matplotlib; returns ``None`` when matplotlib is
    unavailable so the documents still build without it.
    """
    try:
        import os
        import tempfile
        from reportlab.platypus import Image
        from .render import render_cabinet
        panels = None
        if exploded:
            from .geometry import explode_panels
            panels = explode_panels(spec, 0.8)
        path = os.path.join(tempfile.mkdtemp(), "model.png")
        render_cabinet(spec, path, panels=panels)
        w = avail_w
        h = avail_w * 4.2 / 12.0          # render_cabinet uses a 12×4.2 figure
        return Image(path, width=w, height=h)
    except Exception:
        return None


def table_style():
    """The shared house :class:`TableStyle` for the data tables.

    Dark header row, alternating cream body rows, hairline grid. ``report``'s
    purchase-order table additionally right-aligns its trailing numeric columns;
    that one extra rule is layered on by the caller.
    """
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3a352f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3efe9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfc8bd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])


def make_table(header, rows, widths=None, *, extra_style=None):
    """A :class:`Table` with the shared header/repeat-row setup and house style.

    *extra_style* is an optional list of additional ``TableStyle`` commands
    appended after the shared ones (e.g. the purchase order's RIGHT alignment).
    """
    from reportlab.platypus import Table

    t = Table([header] + rows, colWidths=widths, repeatRows=1)
    style = table_style()
    for cmd in (extra_style or []):
        style.add(*cmd)
    t.setStyle(style)
    return t


def paragraph_styles(*, small_leading: float, mini_font: float,
                     mini_space_before: float = 6):
    """The shared ``small`` and ``mini`` paragraph styles.

    The two documents tune the ``small`` body leading and the ``mini`` subhead
    font size / ``spaceBefore`` differently, so those numbers are
    caller-supplied; the rest of the styling (the brown ``mini`` heading color,
    the ``small`` font size, the ``mini`` ``Heading2`` parent) is common.

    Returns ``(styles, small, mini)`` where ``styles`` is the sample stylesheet
    so callers can also pull ``Heading1``/``Heading2``/``BodyText`` from it.
    """
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=small_leading)
    mini = ParagraphStyle("mini", parent=styles["Heading2"], fontSize=mini_font,
                          spaceBefore=mini_space_before,
                          textColor=colors.HexColor("#6b4f3a"))
    return styles, small, mini
