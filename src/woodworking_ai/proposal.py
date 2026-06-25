"""Customer-facing proposal / approval document (PDF).

A CLEAN, client-friendly document — distinct from the shop build package
(:mod:`woodworking_ai.report`). It shows the elevation/projected views with
overall dimensions, a plain-language description of what's being built, the
price, and a sign-off block for approval.

It deliberately omits everything from the shop floor: no joinery, no CNC /
drilling schedule, no cut list, no bench-level assembly steps. The customer
sees what they're buying and what it costs, not how it's made.

Uses **reportlab** (the optional ``pdf`` extra), imported lazily exactly like
:mod:`woodworking_ai.report`; :func:`build_proposal_pdf` raises ``RuntimeError``
with an install hint when reportlab is missing.
"""

from __future__ import annotations

from io import BytesIO

from .estimator import estimate
from .drawings import projected_views
from .units import format_length


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "PDF proposal needs reportlab; install the 'pdf' extra "
            "(pip install -e \".[pdf]\")") from exc


def _elevation_flowable(spec, unit, avail_w):
    """A reportlab Flowable drawing the orthographic views with overall sizes.

    A clean, dimensioned outline — the customer's view of the piece. Unlike the
    shop drawings it carries no per-part IDs, just the exterior with overall
    width/height/depth callouts.
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

    class _Elev(Flowable):
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

                def sx(hh):
                    return bx + (hh - hmin) * scale

                def sy(vv):
                    return by + (vv - vmin) * scale

                c.setFont("Helvetica-Bold", 8)
                c.setFillColorRGB(0.2, 0.2, 0.2)
                c.drawString(bx, by + h_mm * scale + 8, name)
                # Outlines only — fronts filled lightly, no part IDs or detail.
                for b in sorted(boxes, key=lambda b: b.category != "front"):
                    x, y = sx(b.h0), sy(b.v0)
                    bw, bh = (b.h1 - b.h0) * scale, (b.v1 - b.v0) * scale
                    if b.category == "front":
                        c.setStrokeColorRGB(0.55, 0.4, 0.27)
                        c.setFillColorRGB(0.93, 0.88, 0.80)
                        c.rect(x, y, bw, bh, stroke=1, fill=1)
                    else:
                        c.setStrokeColorRGB(0.7, 0.66, 0.6)
                        c.rect(x, y, bw, bh, stroke=1, fill=0)
                # Overall dimension callouts (nominal exterior sizes).
                c.setFillColorRGB(0.25, 0.33, 0.41)
                c.setFont("Helvetica", 7)
                c.drawCentredString(bx + w_mm * scale / 2, by - 10,
                                    format_length(label_dims[0], unit, mark=True))
                c.drawString(bx + w_mm * scale + 4, by + h_mm * scale / 2,
                             format_length(label_dims[1], unit, mark=True))
                ox += margin * 2 + w_mm * scale + gap

    return _Elev()


def _model_image(spec, avail_w):
    """A reportlab Image of the assembled model, or None if matplotlib is absent."""
    try:
        import os
        import tempfile
        from reportlab.platypus import Image
        from .render import render_cabinet
        path = os.path.join(tempfile.mkdtemp(), "model.png")
        render_cabinet(spec, path)
        return Image(path, width=avail_w, height=avail_w * 4.2 / 12.0)
    except Exception:
        return None


def _plain_summary(spec) -> list[str]:
    """Plain-language bullet points describing the piece, for a non-shop reader."""
    out: list[str] = []
    overall = []
    for attr in ("width", "height", "depth"):
        v = getattr(spec, attr, None)
        if isinstance(v, (int, float)):
            overall.append(f"{attr} {v:.0f}mm")
    if overall:
        out.append("Overall size: " + " × ".join(overall) + ".")
    doors = getattr(spec, "doors", None)
    if doors:
        out.append(f"{doors} door(s).")
    drawers = getattr(spec, "drawers", None)
    if drawers:
        out.append(f"{len(drawers)} drawer(s).")
    shelves = getattr(spec, "shelves", None)
    if shelves:
        out.append(f"{shelves} adjustable shelf/shelves.")
    material = getattr(spec, "material", None) or getattr(spec, "species", None)
    if material:
        out.append(f"Material: {material}.")
    finish = getattr(spec, "finish", None)
    if finish:
        out.append(f"Finish: {finish}.")
    brand = getattr(spec, "hardware_brand", None)
    if brand:
        out.append(f"Hardware: {brand}.")
    return out


def build_proposal_pdf(spec, units: str = "metric") -> bytes:
    """Render a customer-facing proposal / approval document as PDF bytes.

    A clean quote the client signs off on — render, dimensioned elevations,
    plain-language spec, price, and a sign-off block. Carries no joinery /
    drilling / cut-list / bench-assembly detail (that lives in the shop build
    package, :func:`woodworking_ai.report.build_package_pdf`).
    """
    _require_reportlab()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)

    unit = units
    est = estimate(spec)

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=11)
    mini = ParagraphStyle("mini", parent=styles["Heading2"], fontSize=11,
                          spaceBefore=6, textColor=colors.HexColor("#6b4f3a"))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            title=f"{spec.name} — proposal",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    avail_w = doc.width
    story = []

    def fl(v):
        return format_length(v, unit, mark=False)

    # --- header ---------------------------------------------------------
    story.append(Paragraph(f"{spec.name} — Proposal", h1))
    story.append(Paragraph(
        "Thank you for the opportunity to quote this piece. Please review the "
        "details below and sign to approve.", small))
    overall = []
    for attr in ("width", "height", "depth"):
        v = getattr(spec, attr, None)
        if isinstance(v, (int, float)):
            overall.append(f"{attr.title()} {fl(v)}")
    if overall:
        story.append(Paragraph(" · ".join(overall), body))
    story.append(Spacer(1, 8))

    # --- visual ---------------------------------------------------------
    img = _model_image(spec, avail_w)
    if img is not None:
        story.append(img)
        story.append(Spacer(1, 6))
    story.append(Paragraph("Elevations &amp; overall dimensions", mini))
    story.append(_elevation_flowable(spec, unit, avail_w))
    story.append(Spacer(1, 8))

    # --- plain-language spec -------------------------------------------
    story.append(Paragraph("What's included", mini))
    for line in _plain_summary(spec):
        story.append(Paragraph("• " + line, small))
    story.append(Spacer(1, 8))

    # --- price ----------------------------------------------------------
    story.append(Paragraph("Price", mini))
    story.append(Paragraph(
        f"<b>{est.currency}{est.total:.2f}</b> — materials, hardware and "
        "finishing, fully built and ready to install.", body))
    story.append(Spacer(1, 14))

    # --- sign-off -------------------------------------------------------
    story.append(Paragraph("Approval", mini))
    story.append(Paragraph(
        "By signing below you approve the design and dimensions above and "
        "authorise work to begin at the price quoted.", small))
    story.append(Spacer(1, 10))
    sign = Table(
        [["Customer signature", "Date"], ["", ""],
         ["Accepted price", f"{est.currency}{est.total:.2f}"]],
        colWidths=[avail_w * 0.6, avail_w * 0.4])
    sign.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b6258")),
        ("LINEBELOW", (0, 1), (-1, 1), 0.75, colors.HexColor("#888")),
        ("TOPPADDING", (0, 1), (-1, 1), 18),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(sign)

    doc.build(story)
    return buf.getvalue()
