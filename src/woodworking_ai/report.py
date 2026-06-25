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


def _nest_flowables(cl, avail_w, unit):
    """One Flowable per sheet of the cutting layout, each part drawn and labelled
    with its ID — the "cut these out and label them" diagram. Returns a list so
    reportlab can page-break between sheets.
    """
    from reportlab.platypus import Flowable
    from .estimator import SheetSize
    from .packing import pack

    sheet = SheetSize()
    # Group by physical stock so same-material parts share a sheet, then title
    # each sheet by the stock you actually bought (matches the shopping list).
    groups: dict = {}
    meta: dict = {}
    for p in cl.parts:
        if p.is_solid_lumber:
            continue
        key = (p.form or p.material, p.form, p.species, p.thickness)
        items = groups.setdefault(key, [])
        meta[key] = (p.material, p.form, p.species)
        for i in range(p.qty):
            lbl = p.id if p.qty == 1 else f"{p.id}.{i + 1}"
            seq = "front" if p.material == "door/front" else ""
            items.append((p.length, p.width, lbl, p.grain, seq))

    scale = avail_w / sheet.length
    sheet_h = sheet.width * scale

    class _SheetFlow(Flowable):
        def __init__(self, title, placements):
            super().__init__()
            self.title = title
            self.placements = placements

        def wrap(self, _w, _h):
            return (avail_w, sheet_h + 22)

        def draw(self):
            c = self.canv
            c.setFont("Helvetica-Bold", 8)
            c.setFillColorRGB(0.23, 0.18, 0.13)
            c.drawString(0, sheet_h + 8, self.title)
            c.setStrokeColorRGB(0.5, 0.45, 0.4)
            c.setLineWidth(0.8)
            c.rect(0, 0, sheet.length * scale, sheet_h, stroke=1, fill=0)
            for (x, y, lng, wid, label) in self.placements:
                rx = x * scale
                ry = (sheet.width - y - wid) * scale
                c.setStrokeColorRGB(0.61, 0.42, 0.26)
                c.setFillColorRGB(0.95, 0.91, 0.84)
                c.rect(rx, ry, lng * scale, wid * scale, stroke=1, fill=1)
                c.setFillColorRGB(0.23, 0.18, 0.13)
                c.setFont("Helvetica-Bold", 6.5)
                c.drawString(rx + 2, ry + wid * scale / 2 - 3, label)

    from .stock import stock_label
    from .materials import stock_name
    flows = []
    for key, items in sorted(groups.items()):
        thk = key[-1]
        mat, form, species = meta[key]
        name = stock_name(form, species, solid=False, fallback=stock_label(mat))
        sheets, _oversize = pack(items, sheet)
        for si, placements in enumerate(sheets):
            flows.append(_SheetFlow(
                f"{name} {thk:.0f}mm — sheet {si + 1}/{len(sheets)}",
                placements))
    return flows


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

    from .cutlist import SOLID_LUMBER_MATERIALS

    # --- cover -----------------------------------------------------------
    story.append(Paragraph(f"🪵 {spec.name}", h1))
    story.append(Paragraph("Assembly instructions — shop the BOM, cut &amp; "
                           "process all parts, build the sub-assemblies, then the "
                           "final assembly", small))
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

    sec = [0]

    def heading(title):
        sec[0] += 1
        story.append(Paragraph(f"{sec[0]} · {title}", h2))

    # 1 · Shopping list — buy everything first ---------------------------
    from .finishing import finishing_schedule
    from .stock import stock_label, stock_product
    from .materials import stock_name, product_hint
    heading("Shopping list — buy this first")
    story.append(Paragraph(
        "Everything to buy and have on hand before you start. The stock below is "
        "the raw sheet/board material — every part (§3) is cut from it.", small))
    story.append(Paragraph("Sheet goods (full sheets to buy)", mini))
    story.append(tbl(
        ["Stock to buy", "Typical product", "Thickness", "Sheets"],
        [[stock_name(g.form, g.species, fallback=stock_label(g.material)),
          product_hint(g.form, stock_product(g.material)), fl(g.thickness),
          g.sheets] for g in est.groups] or [["—", "", "", ""]]))
    if est.lumber_groups:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Solid lumber (by the board foot)", mini))
        story.append(tbl(
            ["Stock to buy", "Typical product", "Thickness", "Board feet"],
            [[stock_name(g.form, g.species, solid=True,
                         fallback=stock_label(g.material)),
              product_hint(g.form, stock_product(g.material)), fl(g.thickness),
              f"{g.board_feet:.1f}"] for g in est.lumber_groups]))
    extras = []
    if est.edge_banding_m:
        extras.append(f"Edge banding: ~{est.edge_banding_m:.1f} m")
    fin = finishing_schedule(spec)
    if fin["coats"]:
        extras.append(
            f"Finish ({fin['type']}): ~{fin['litres']:.1f} L for {fin['coats']} "
            f"coats over {fin['area_m2']:.1f} m²")
    if extras:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Consumables: " + " · ".join(extras), small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Hardware &amp; fasteners (order list)", mini))
    story.append(tbl(
        ["Item", "Qty", "Brand", "SKU", "Notes"],
        [[h.name, h.qty, h.brand, h.sku, h.notes] for h in cl.hardware]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Estimated total: {est.currency}{est.total:.2f}</b> — "
        f"{est.total_sheets} sheet(s), {est.total_board_feet:.1f} bd ft, "
        f"{sum(h.qty for h in cl.hardware)} hardware items.", body))
    story.append(PageBreak())

    # 2 · Overview -------------------------------------------------------
    heading("Overview — what you're building")
    img = _model_image(spec, avail_w, exploded=True)
    if img is not None:
        story.append(img)
    names = [s.name for s in plan.subassemblies
             if s.name not in ("Preparation", "Final assembly")]
    story.append(Paragraph(
        "<b>Build order:</b> cut &amp; label every part, process them (joinery + "
        "drilling) while flat, build each sub-assembly, then the final assembly.",
        small))
    story.append(Paragraph("Sub-assemblies, in build order: " + ", ".join(names)
                           + " → Final assembly.", small))
    from .materials import build_hints
    hints = build_hints(spec)
    if hints:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Material notes", mini))
        for _sev, _f, msg in hints:
            story.append(Paragraph("• " + msg, small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Dimensioned drawings", mini))
    story.append(_drawings_flowable(spec, unit, avail_w))
    story.append(PageBreak())

    # 2 · Cut & label all parts ------------------------------------------
    heading("Cut &amp; label all parts")
    story.append(Paragraph(
        "Cut every part from the stock below and write its ID on it. The rest of "
        "this manual refers to parts by ID, so label as you go.", small))
    nest = _nest_flowables(cl, avail_w, unit)
    if nest:
        story.append(Paragraph("Cutting layout (sheet goods)", mini))
        for f in nest:
            story.append(f)
            story.append(Spacer(1, 8))
    solids = [p for p in cl.parts if p.material in SOLID_LUMBER_MATERIALS]
    if solids:
        story.append(Paragraph(
            "From solid stock (by the board foot): " + ", ".join(
                f"{p.id} {p.name}×{p.qty}" for p in solids), small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Cut list", mini))
    story.append(tbl(
        ["ID", "Part", "Qty", f"L ({unit[:3]})", "W", "Thk", "From stock", "Grain"],
        [[p.id, p.name, p.qty, fl(p.length), fl(p.width), fl(p.thickness),
          stock_name(p.form, p.species, solid=p.is_solid_lumber,
                     fallback=stock_label(p.material)), p.grain]
         for p in cl.parts]))
    story.append(PageBreak())

    # 3 · Process all parts ----------------------------------------------
    heading("Process all parts (while flat)")
    story.append(Paragraph(
        "Complete all joinery and drilling now, before assembly — it is far "
        "easier on flat panels. Each row references the part by ID.", small))
    if joint.ops:
        story.append(Paragraph("Joinery", mini))
        story.append(tbl(
            ["ID", "Part", "Operation", "Tool", "W", "D", "Where"],
            [[o.part_id, o.part, o.operation, o.tool,
              fl(o.width) if o.width else "", fl(o.depth) if o.depth else "",
              o.reference] for o in joint.ops]))
        story.append(Spacer(1, 8))
    if drill.ops:
        story.append(Paragraph("Drilling (32mm system)", mini))
        story.append(tbl(
            ["ID", "Part", "Operation", "Holes", "Note"],
            [[o.part_id, o.part, o.operation, len(o.holes), o.note]
             for o in drill.ops]))
    story.append(PageBreak())

    # 5..N · Build each sub-assembly from the cut, processed parts --------
    for sub in plan.subassemblies:
        if sub.name in ("Preparation", "Final assembly"):
            continue
        sp = parts_of(sub)
        heading(f"Build: {sub.name}")
        story.append(Paragraph(f"<i>{sub.detail}</i>", small))
        if sp:
            story.append(Paragraph(
                "Parts (already cut &amp; processed in steps 2–3):", mini))
            story.append(_parts_diagram(sp, avail_w, unit))
            story.append(Spacer(1, 4))
        story.append(Paragraph("Assemble", mini))
        # The joinery was cut in step 3, so the build steps are assembly only.
        asm = [s for s in sub.steps if s.category != "joinery"]
        for i, s in enumerate(asm, start=1):
            story.append(Paragraph(f"<b>{i}. {s.title}</b>", body))
            story.append(Paragraph(s.detail, small))
            if s.hardware:
                story.append(Paragraph("↳ " + ", ".join(s.hardware), small))
        story.append(Spacer(1, 10))

    # Final · put the sub-assemblies together ----------------------------
    final = next((s for s in plan.subassemblies if s.name == "Final assembly"),
                 None)
    if final:
        story.append(PageBreak())
        heading("Final assembly")
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
