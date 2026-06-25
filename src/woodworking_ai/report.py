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

import math
from io import BytesIO

from .cutlist import generate_cutlist
from .estimator import estimate
from .drilling import drilling_schedule
from .joinery import joinery_schedule
from .assembly_steps import assembly_plan
from .units import format_length
from . import pdf_common


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "PDF build package needs reportlab; install the 'pdf' extra "
            "(pip install -e \".[pdf]\")") from exc


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
        key = p.stock_key
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


def build_purchase_order_pdf(spec, units: str = "metric") -> bytes:
    """Render a supplier-grouped purchase order for *spec* as PDF bytes.

    One table per supplier (sheet goods, lumber yard, each hardware brand, edge
    banding, finish, in-house labour), each line carrying its spec/SKU, quantity,
    unit price and line total, with per-supplier subtotals and a grand total that
    reconciles with the quote. Uses reportlab, guarded like the build package.
    """
    _require_reportlab()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer)

    from .purchasing import purchase_order
    po = purchase_order(spec)
    c = po.currency

    styles, small, mini = pdf_common.paragraph_styles(
        small_leading=10, mini_font=10)
    h1 = styles["Heading1"]
    body = styles["BodyText"]

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=f"{spec.name} — purchase order",
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm)
    story = []

    def tbl(header, rows, widths=None):
        return pdf_common.make_table(
            header, rows, widths,
            extra_style=[(("ALIGN", (-3, 1), (-1, -1), "RIGHT"))])

    story.append(Paragraph(f"🧾 Purchase order — {spec.name}", h1))
    story.append(Paragraph(
        "Everything to buy to build this, grouped by the supplier (or hardware "
        "brand) you raise the order against. The grand total reconciles with the "
        "cost estimate.", small))
    story.append(Spacer(1, 6))

    for supplier, lines in po.lines_by_supplier().items():
        story.append(Paragraph(supplier, mini))
        rows = [[ln.item, ln.spec or ln.sku, f"{ln.qty:g}", ln.unit,
                 f"{c}{ln.unit_price:.2f}", f"{c}{ln.line_total:.2f}"]
                for ln in lines]
        rows.append(["", "", "", "", "Subtotal",
                     f"{c}{po.supplier_total(supplier):.2f}"])
        story.append(tbl(
            ["Item", "Spec / SKU", "Qty", "Unit", "Unit price", "Line total"],
            rows))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Grand total: {c}{po.grand_total:.2f}</b>", body))
    doc.build(story)
    return buf.getvalue()


def build_package_pdf(spec, units: str = "metric") -> bytes:
    """Render the full build package for *spec* as PDF bytes."""
    _require_reportlab()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak)

    unit = units
    cl = generate_cutlist(spec)
    est = estimate(spec, cutlist=cl)
    drill = drilling_schedule(spec)
    joint = joinery_schedule(spec)
    plan = assembly_plan(spec)

    styles, small, mini = pdf_common.paragraph_styles(
        small_leading=10, mini_font=9.5, mini_space_before=4)
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"{spec.name} — build package",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    avail_w = doc.width
    story = []

    def fl(v):
        return format_length(v, unit, mark=False)

    def tbl(header, rows, widths=None):
        return pdf_common.make_table(header, rows, widths)

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
    img = pdf_common.model_image(spec, avail_w, exploded=True)
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
    story.append(pdf_common.elevation_flowable(
        spec, unit, avail_w, show_ids=True, colors=pdf_common.SHOP_COLORS))
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

    # N · Appliance schedule — only when the design has appliances ---------
    from .appliances import appliance_schedule
    appliances = appliance_schedule(spec)
    if appliances:
        heading("Appliance schedule")
        story.append(Paragraph(
            "Each appliance, where it lives, and the rough-in the trades need to "
            "bring to the opening before the cabinets close it in.", small))
        story.append(tbl(
            ["Type", "Host", "Cutout", "Clearances", "Panels", "Rough-in"],
            [[a["type"], a["host"], a["cutout"], a["clearances"],
              a["panels"], a["rough_in"]] for a in appliances]))
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
        img2 = pdf_common.model_image(spec, avail_w, exploded=False)
        if img2 is not None:
            story.append(img2)
        for s in final.steps:
            story.append(Paragraph(f"<b>{s.number}. {s.title}</b>", body))
            story.append(Paragraph(s.detail, small))
            if s.hardware:
                story.append(Paragraph("↳ " + ", ".join(s.hardware), small))

    doc.build(story)
    return buf.getvalue()


def build_template_pdf(spec, part_id: str | None = None,
                       *, page: str = "letter", units: str = "metric") -> bytes:
    """A full-scale (1:1) tiled PDF template for one part, as PDF bytes.

    Prints a part's finished outline at true size, tiled across as many
    ``page`` (``"letter"`` or ``"a4"``) sheets as it takes, with an overlap
    margin and registration tick marks so the sheets butt together. Print at
    100% (no "fit to page"), trim to the ticks, tape the grid, then spray-glue
    to the stock and cut to the line — the workflow hobbyists use for tapers,
    splayed legs and frame profiles.

    Without *part_id* the largest cut-list part is templated (it's the one that
    most needs a full-size pattern). Raises ``RuntimeError`` if reportlab is
    missing (mirrors the other PDF exports) and ``ValueError`` for an unknown
    *part_id* or *page*.
    """
    _require_reportlab()
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.pdfgen import canvas

    pages = {"letter": letter, "a4": A4}
    pname = page.lower()
    if pname not in pages:
        raise ValueError(f"unknown page size: {page!r} (use 'letter' or 'a4')")
    page_w, page_h = pages[pname]

    cl = generate_cutlist(spec)
    if not cl.parts:
        raise ValueError("spec has no parts to template")
    if part_id is None:
        part = max(cl.parts, key=lambda p: p.length * p.width)
    else:
        part = next((p for p in cl.parts if p.id == part_id), None)
        if part is None:
            raise ValueError(f"unknown part id: {part_id!r}")

    # reportlab points are 1/72". 1mm = 72/25.4 pt. Drawing at this scale puts
    # the outline at true physical size on the printed page.
    pt_per_mm = 72.0 / 25.4
    # The outline is the finished length x width rectangle.
    part_l = max(part.length, part.width)   # mm
    part_w = min(part.length, part.width)   # mm
    if page_w > page_h:                     # template pages are portrait-first
        page_w, page_h = page_h, page_w

    margin = 12.0 * pt_per_mm                # registration / glue overlap (~12mm)
    overlap = 8.0 * pt_per_mm                # shared band between adjacent tiles
    # Live drawing area per tile and how far it advances (less the shared band).
    tile_w = page_w - 2 * margin
    tile_h = page_h - 2 * margin
    span_x = part_l * pt_per_mm
    span_y = part_w * pt_per_mm
    step_x = tile_w - overlap
    step_y = tile_h - overlap
    cols = max(1, math.ceil((span_x - overlap) / step_x))
    rows = max(1, math.ceil((span_y - overlap) / step_y))

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    def _ticks():
        c.setLineWidth(0.4)
        c.setStrokeColorRGB(0, 0, 0)
        m = margin
        for (x, y) in ((m, m), (page_w - m, m), (m, page_h - m),
                       (page_w - m, page_h - m)):
            c.line(x - 6, y, x + 6, y)
            c.line(x, y - 6, x, y + 6)

    label = f"{part.id} {part.name}"
    size_txt = (f"{format_length(part.length, units, mark=True)} x "
                f"{format_length(part.width, units, mark=True)}")
    for r in range(rows):
        for col in range(cols):
            # This tile's origin in part space (pt) from the part's bottom-left;
            # tiles advance by ``step`` so each shares an ``overlap`` band with
            # its neighbour for taping.
            off_x = col * step_x
            off_y = r * step_y
            _ticks()
            c.setFont("Helvetica", 7)
            c.setFillColorRGB(0.3, 0.3, 0.3)
            c.drawString(margin, page_h - margin + 4,
                         f"{label}  {size_txt}  tile r{r + 1}c{col + 1} "
                         f"of {rows}x{cols} - PRINT AT 100%")
            # The part outline, clipped to this tile's live area, drawn at 1:1.
            c.saveState()
            path = c.beginPath()
            path.rect(margin, margin, tile_w, tile_h)
            c.clipPath(path, stroke=0, fill=0)
            c.setLineWidth(1.0)
            c.setStrokeColorRGB(0, 0, 0)
            x0 = margin - off_x
            y0 = margin - off_y
            c.rect(x0, y0, span_x, span_y, stroke=1, fill=0)
            c.restoreState()
            c.showPage()
    c.save()
    return buf.getvalue()
