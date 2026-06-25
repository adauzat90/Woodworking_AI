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
from .assembly_steps import assembly_plan
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


def _parts_diagram(parts, avail_w, unit):
    """A Flowable laying each part out as a scaled, labelled rectangle.

    The IKEA-style "here are the pieces" view: one tile per part, drawn to a
    shared scale so relative sizes read true, captioned with its ID, quantity
    and finished size.
    """
    from reportlab.platypus import Flowable

    faces = [(max(p.length, p.width), min(p.length, p.width)) for p in parts]
    max_dim = max((f[0] for f in faces), default=1.0)
    scale = min(96.0 / max_dim, 0.12)
    label_h, gap = 18.0, 12.0
    placed, x, y, row_h = [], 0.0, 0.0, 0.0
    for p, (lng, wid) in zip(parts, faces):
        pw, ph = max(lng * scale, 8.0), max(wid * scale, 8.0)
        cell_w = max(pw, 46.0)
        if x + cell_w > avail_w and x > 0:
            y += row_h + gap
            x, row_h = 0.0, 0.0
        placed.append((p, x, y, pw, ph))
        x += cell_w + gap
        row_h = max(row_h, ph + label_h)
    total_h = y + row_h

    class _PD(Flowable):
        def wrap(self, _w, _h):
            return (avail_w, total_h)

        def draw(self):
            c = self.canv
            for (p, px, py, pw, ph) in placed:
                top = total_h - py
                yb = top - ph
                c.setStrokeColorRGB(0.61, 0.42, 0.26)
                c.setFillColorRGB(0.95, 0.91, 0.84)
                c.rect(px, yb, pw, ph, stroke=1, fill=1)
                c.setFillColorRGB(0.23, 0.18, 0.13)
                c.setFont("Helvetica-Bold", 6.5)
                c.drawString(px, yb - 9, f"{p.id}×{p.qty} {p.name[:16]}")
                c.setFont("Helvetica", 5.5)
                c.setFillColorRGB(0.4, 0.36, 0.3)
                c.drawString(px, yb - 15,
                             f"{format_length(p.length, unit)}×"
                             f"{format_length(p.width, unit)}")
    return _PD()


def _model_image(spec, avail_w, *, exploded: bool):
    """A reportlab Image of the model (exploded or assembled), or None.

    Rendered headlessly with matplotlib; returns None when matplotlib is
    unavailable so the package still builds without it.
    """
    try:
        import os
        import tempfile
        from reportlab.platypus import Image
        from .render import render_cabinet
        from .geometry import explode_panels
        panels = explode_panels(spec, 0.8) if exploded else None
        path = os.path.join(tempfile.mkdtemp(), "model.png")
        render_cabinet(spec, path, panels=panels)
        w = avail_w
        h = avail_w * 4.2 / 12.0          # render_cabinet uses a 12×4.2 figure
        return Image(path, width=w, height=h)
    except Exception:
        return None


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
    plan = assembly_plan(spec)

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

    sub_style = ParagraphStyle("sub", parent=h2, fontSize=13, spaceBefore=6,
                               textColor=colors.HexColor("#9c6b43"))
    mini = ParagraphStyle("mini", parent=h2, fontSize=9.5, spaceBefore=4,
                          textColor=colors.HexColor("#6b4f3a"))
    by_id = {p.id: p for p in cl.parts}

    def parts_of(sub):
        seen, out = set(), []
        for pid in sub.part_ids:
            p = by_id.get(pid)
            if p and pid not in seen:
                seen.add(pid)
                out.append(p)
        return out

    def joinery_of(sub):
        ids = set(sub.part_ids)
        return [o for o in joint.ops if o.part_id in ids]

    def drilling_of(sub):
        ids = set(sub.part_ids)
        return [o for o in drill.ops if o.part_id in ids]

    # --- cover -----------------------------------------------------------
    story.append(Paragraph(f"🪵 {spec.name}", h1))
    story.append(Paragraph("Assembly instructions — overview, then make &amp; "
                           "build each sub-assembly, then put it together", small))
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
    story.append(Spacer(1, 6))

    # --- overview: exploded view + everything you need -------------------
    story.append(Paragraph("1 · Overview — what it's made of", h2))
    img = _model_image(spec, avail_w, exploded=True)
    if img is not None:
        story.append(img)
    story.append(Paragraph(
        "The piece breaks into the sub-assemblies below. Build each one, then "
        "join them in Final assembly.", small))
    names = [s.name for s in plan.subassemblies
             if s.name not in ("Preparation", "Final assembly")]
    story.append(Paragraph("Sub-assemblies: " + ", ".join(names), small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Dimensioned drawings", mini))
    story.append(_drawings_flowable(spec, unit, avail_w))
    story.append(PageBreak())

    # --- all parts + hardware + nesting (the "in the box" inventory) -----
    story.append(Paragraph("2 · All parts &amp; hardware", h2))
    story.append(Paragraph("Cut list", mini))
    story.append(tbl(
        ["ID", "Part", "Qty", f"L ({unit[:3]})", "W", "Thk", "Material", "Grain"],
        [[p.id, p.name, p.qty, fl(p.length), fl(p.width), fl(p.thickness),
          p.material, p.grain] for p in cl.parts]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Hardware / BOM", mini))
    story.append(tbl(
        ["Item", "Qty", "Brand", "SKU", "Notes"],
        [[h.name, h.qty, h.brand, h.sku, h.notes] for h in cl.hardware]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Sheet nesting", mini))
    story.append(tbl(
        ["Material", "Thk", "Parts", "Sheets", "Used %", "Oversize"],
        [[g.material, fl(g.thickness), g.part_count, g.sheets,
          f"{g.utilization * 100:.0f}", g.oversize] for g in est.groups]))

    # Before you begin: the preparation steps (mill + drill).
    prep = next((s for s in plan.subassemblies if s.name == "Preparation"), None)
    if prep:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Before you begin", mini))
        for s in prep.steps:
            story.append(Paragraph(f"<b>{s.number}. {s.title}</b>", body))
            story.append(Paragraph(s.detail, small))
    story.append(PageBreak())

    # --- one detailed section per buildable sub-assembly -----------------
    step_no = 3
    for sub in plan.subassemblies:
        if sub.name in ("Preparation", "Final assembly"):
            continue
        sp = parts_of(sub)
        story.append(Paragraph(f"{step_no} · {sub.name}", sub_style))
        story.append(Paragraph(f"<i>{sub.detail}</i>", small))
        if sp:
            story.append(Paragraph("Parts you'll need", mini))
            story.append(_parts_diagram(sp, avail_w, unit))
            story.append(tbl(
                ["ID", "Part", "Qty", f"L ({unit[:3]})", "W", "Thk", "Material"],
                [[p.id, p.name, p.qty, fl(p.length), fl(p.width),
                  fl(p.thickness), p.material] for p in sp]))
            story.append(Spacer(1, 6))
        make = joinery_of(sub)
        drills = drilling_of(sub)
        if make or drills:
            story.append(Paragraph("Make the parts", mini))
            if make:
                story.append(tbl(
                    ["ID", "Part", "Operation", "Tool", "W", "D", "Where"],
                    [[o.part_id, o.part, o.operation, o.tool,
                      fl(o.width) if o.width else "",
                      fl(o.depth) if o.depth else "", o.reference]
                     for o in make]))
            if drills:
                story.append(Paragraph(
                    "Drilling: " + "; ".join(
                        f"{o.part_id or o.part} — {o.operation} "
                        f"({len(o.holes)} holes)" for o in drills), small))
            story.append(Spacer(1, 6))
        story.append(Paragraph("Assemble", mini))
        for s in sub.steps:
            story.append(Paragraph(f"<b>{s.number}. {s.title}</b>", body))
            story.append(Paragraph(s.detail, small))
            if s.hardware:
                story.append(Paragraph("↳ " + ", ".join(s.hardware), small))
        story.append(Spacer(1, 10))
        step_no += 1

    # --- final assembly: put the sub-assemblies together -----------------
    final = next((s for s in plan.subassemblies if s.name == "Final assembly"),
                 None)
    if final:
        story.append(PageBreak())
        story.append(Paragraph(f"{step_no} · Final assembly", sub_style))
        story.append(Paragraph(f"<i>{final.detail}</i>", small))
        img2 = _model_image(spec, avail_w, exploded=False)
        if img2 is not None:
            story.append(img2)
        for s in final.steps:
            story.append(Paragraph(f"<b>{s.number}. {s.title}</b>", body))
            story.append(Paragraph(s.detail, small))
            if s.hardware:
                story.append(Paragraph("↳ " + ", ".join(s.hardware), small))

    doc.build(story)
    return buf.getvalue()
