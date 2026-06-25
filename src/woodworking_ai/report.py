"""Printable build package (PDF).

Assembles everything a shop carries to the bench into one document: a cover with
the overall sizes, the dimensioned drawings, the labelled cut list, the
orderable hardware BOM, the sheet-nesting summary, the drilling schedule, the
joinery setup sheet, and the step-by-step assembly sequence — all cross-
referenced by the shared part IDs.

Uses **reportlab** (the optional ``pdf`` extra). Import is deferred so the rest
of the package runs without it; :func:`build_package_pdf` raises ``RuntimeError``
with an install hint when it is missing, mirroring how the CAD exports behave.
"""

from __future__ import annotations

from io import BytesIO

from .cutlist import generate_cutlist
from .estimator import estimate
from .drilling import drilling_schedule
from .joinery import joinery_schedule
from .assembly_steps import assembly_sequence
from .drawings import projected_views
from .units import format_length


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "PDF build package needs reportlab; install the 'pdf' extra "
            "(pip install -e \".[pdf]\")") from exc


def _drawings_flowable(spec, unit, avail_w):
    """A reportlab Flowable that draws the three orthographic views to scale."""
    from reportlab.platypus import Flowable

    views = projected_views(spec)
    margin = 30.0
    gap = 24.0
    extent = 1.0
    for (_n, _h, _v, _b, bounds, _ld) in views:
        extent = max(extent, bounds[1] - bounds[0], bounds[3] - bounds[2])
    # Fit all three views (plus margins/gaps) across the available width.
    raw_w = sum((b[1] - b[0]) for (_n, _h, _v, _bx, b, _ld) in views)
    n = len(views)
    scale = (avail_w - 2 * margin * n - gap * (n - 1)) / max(raw_w, 1.0)
    scale = max(min(scale, 0.25), 0.02)
    height = margin * 2 + max((b[3] - b[2]) for (*_, b, _ld) in views) * scale + 24

    class _Views(Flowable):
        def wrap(self, w, h):
            return (avail_w, height)

        def draw(self):
            c = self.canv
            ox = 0.0
            for (name, _h, _v, boxes, bounds, label_dims) in views:
                hmin, hmax, vmin, vmax = bounds
                w_mm, h_mm = hmax - hmin, vmax - vmin
                bx = ox + margin
                by = margin

                def sx(hh):
                    return bx + (hh - hmin) * scale

                def sy(vv):
                    return by + (vv - vmin) * scale

                c.setFont("Helvetica-Bold", 8)
                c.drawString(bx, by + h_mm * scale + 8, name)
                for b in sorted(boxes, key=lambda b: b.category != "front"):
                    x, y = sx(b.h0), sy(b.v0)
                    bw, bh = (b.h1 - b.h0) * scale, (b.v1 - b.v0) * scale
                    if b.category == "front":
                        c.setStrokeColorRGB(0.61, 0.42, 0.26)
                        c.setFillColorRGB(0.91, 0.85, 0.75)
                        c.rect(x, y, bw, bh, stroke=1, fill=1)
                        if b.part_id and bw > 14 and bh > 10:
                            c.setFillColorRGB(0.35, 0.27, 0.2)
                            c.setFont("Helvetica-Bold", 6)
                            c.drawCentredString(x + bw / 2, y + bh / 2 - 2, b.part_id)
                    else:
                        c.setStrokeColorRGB(0.73, 0.69, 0.64)
                        c.rect(x, y, bw, bh, stroke=1, fill=0)
                # Overall dimension labels (nominal sizes).
                c.setFillColorRGB(0.25, 0.33, 0.41)
                c.setFont("Helvetica", 7)
                c.drawCentredString(bx + w_mm * scale / 2, by - 10,
                                    format_length(label_dims[0], unit, mark=True))
                c.drawString(bx + w_mm * scale + 4, by + h_mm * scale / 2,
                             format_length(label_dims[1], unit, mark=True))
                ox += margin * 2 + w_mm * scale + gap

    return _Views()


def build_package_pdf(spec, units: str = "metric") -> bytes:
    """Render the full build package for *spec* as PDF bytes."""
    _require_reportlab()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)

    unit = units
    cl = generate_cutlist(spec)
    est = estimate(spec, cutlist=cl)
    drill = drilling_schedule(spec)
    joint = joinery_schedule(spec)
    seq = assembly_sequence(spec)

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"{spec.name} — build package",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    avail_w = doc.width
    story = []

    def fl(v):
        return format_length(v, unit, mark=False)

    def tbl(header, rows, widths=None):
        data = [header] + rows
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3a352f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f3efe9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfc8bd")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    # --- cover -----------------------------------------------------------
    story.append(Paragraph(f"🪵 {spec.name}", h1))
    story.append(Paragraph("Build package — drawings, cut list, BOM, drilling, "
                           "joinery and assembly", small))
    overall = []
    for attr in ("width", "height", "depth"):
        v = getattr(spec, attr, None)
        if isinstance(v, (int, float)):
            overall.append(f"{attr.title()} {fl(v)}")
    if overall:
        story.append(Paragraph(" · ".join(overall), body))
    story.append(Paragraph(
        f"{sum(p.qty for p in cl.parts)} parts · "
        f"{sum(h.qty for h in cl.hardware)} hardware items · "
        f"{est.total_sheets} sheet(s) · {est.currency}{est.total:.2f} estimated",
        body))
    story.append(Spacer(1, 8))

    # --- drawings --------------------------------------------------------
    story.append(Paragraph("Drawings", h2))
    story.append(_drawings_flowable(spec, unit, avail_w))
    story.append(PageBreak())

    # --- cut list --------------------------------------------------------
    story.append(Paragraph("Cut list", h2))
    story.append(tbl(
        ["ID", "Part", "Qty", f"L ({unit[:3]})", "W", "Thk", "Material", "Grain"],
        [[p.id, p.name, p.qty, fl(p.length), fl(p.width), fl(p.thickness),
          p.material, p.grain] for p in cl.parts]))
    story.append(Spacer(1, 10))

    # --- hardware / BOM --------------------------------------------------
    story.append(Paragraph("Hardware / BOM", h2))
    story.append(tbl(
        ["Item", "Qty", "Brand", "SKU", "Notes"],
        [[h.name, h.qty, h.brand, h.sku, h.notes] for h in cl.hardware]))
    story.append(Spacer(1, 10))

    # --- nesting summary -------------------------------------------------
    story.append(Paragraph("Sheet nesting", h2))
    story.append(tbl(
        ["Material", "Thk", "Parts", "Sheets", "Used %", "Oversize"],
        [[g.material, fl(g.thickness), g.part_count, g.sheets,
          f"{g.utilization * 100:.0f}", g.oversize] for g in est.groups]))
    story.append(PageBreak())

    # --- drilling --------------------------------------------------------
    story.append(Paragraph("Drilling schedule (32mm system)", h2))
    story.append(tbl(
        ["ID", "Part", "Operation", "Holes", "Note"],
        [[o.part_id, o.part, o.operation, len(o.holes), o.note]
         for o in drill.ops]))
    story.append(Spacer(1, 10))

    # --- joinery ---------------------------------------------------------
    story.append(Paragraph("Joinery setup", h2))
    story.append(tbl(
        ["ID", "Part", "Operation", "Tool", "W", "D", "Where"],
        [[o.part_id, o.part, o.operation, o.tool,
          fl(o.width) if o.width else "", fl(o.depth) if o.depth else "",
          o.reference] for o in joint.ops]))
    story.append(PageBreak())

    # --- assembly --------------------------------------------------------
    story.append(Paragraph("Assembly sequence", h2))
    for s in seq.steps:
        ids = f"  [{', '.join(s.part_ids)}]" if s.part_ids else ""
        story.append(Paragraph(f"<b>{s.number}. {s.title}</b>{ids}", body))
        story.append(Paragraph(s.detail, small))
        if s.hardware:
            story.append(Paragraph("↳ " + ", ".join(s.hardware), small))
        story.append(Spacer(1, 3))

    doc.build(story)
    return buf.getvalue()
