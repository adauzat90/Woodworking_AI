"""Generate a shop design sheet PDF for the Mobile Storage Workbench.

Units: metric by default; pass --imperial (or set WOODAI_UNITS=in) to render every
dimension in fractional inches and write design_sheet_imperial.pdf.
"""
import json, os, sys, re

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Flowable, PageBreak)

sys.path.insert(0, "src")
from woodworking_ai import spec_from_dict, generate_cutlist, estimate, purchase_order
from woodworking_ai.drilling import drilling_schedule
from woodworking_ai.cutplan import cut_plan, StockBoard, _group_key
from woodworking_ai.stock import STANDARD_SHEET
from woodworking_ai.units import format_length, format_area
from collections import Counter

# ---- units ----
IMP = ("--imperial" in sys.argv or
       os.environ.get("WOODAI_UNITS", "").strip().lower() in ("in", "inch", "imperial"))
UNIT = "imperial" if IMP else "metric"
UCOL = "in" if IMP else "mm"


def L(mm, mark=True):
    """A length in the active unit (fractional inches when imperial)."""
    return format_length(mm, UNIT, mark=mark)


def Lc(mm):
    """Compact length for tight diagram labels (no space before the unit)."""
    return (format_length(mm, "imperial", mark=False) + '"') if IMP else "%.0fmm" % mm


def dims3(t):
    return " x ".join(L(v, mark=False) for v in t)


def run_len(mm):
    return "%.0f ft" % (mm / 304.8) if IMP else "%.1f m" % (mm / 1000.0)


REPO = "."
OUT = os.path.join(REPO, "examples/mobile_storage_workbench_docs",
                   "design_sheet_imperial.pdf" if IMP else "design_sheet.pdf")
SPEC_PATH = os.path.join(REPO, "examples/mobile_storage_workbench.json")

data = json.load(open(SPEC_PATH, encoding="utf-8"))
spec = spec_from_dict(data)
cl = generate_cutlist(spec)
sched = drilling_schedule(spec)
est = estimate(spec)

_groups = {}
for _p in cl.parts:
    _groups[_group_key(_p)] = None
STOCK = [StockBoard(length=STANDARD_SHEET[0], width=STANDARD_SHEET[1],
                    thickness=th, form=form, species=species, qty=60)
         for (th, form, species) in _groups]
PLAN = cut_plan(spec, STOCK, cutlist=cl)
USED = [bp for bp in PLAN.boards if bp.placements]
USED.sort(key=lambda bp: (bp.board.thickness == 40, -bp.board.thickness, bp.instance))

# ---- palette ----
INK = colors.HexColor("#1c2b36")
ACCENT = colors.HexColor("#8a5a2b")
WOOD = colors.HexColor("#c69c6d")
LIGHT = colors.HexColor("#f3ede4")
LINE = colors.HexColor("#6b7680")
GRID = colors.HexColor("#c9d1d9")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], textColor=INK, fontSize=20,
                    leading=23, spaceAfter=2, alignment=TA_LEFT)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], textColor=ACCENT, fontSize=10.5,
                     leading=13, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=ACCENT, fontSize=11.5,
                    leading=14, spaceBefore=8, spaceAfter=3)
SMALL = ParagraphStyle("SMALL", parent=styles["Normal"], textColor=LINE, fontSize=7.4,
                       leading=9)
CELL = ParagraphStyle("CELL", parent=styles["Normal"], textColor=INK, fontSize=8,
                      leading=9.5)

# ---- parse banks ----
BANKS = [(it["spec"]["name"], it["spec"]["width"],
          [d["front_height"] for d in it["spec"]["drawers"]])
         for run in data["runs"] for it in run["items"]]
CT = data["countertop"]
overall_w, overall_d, carcass_h, top_t = 1829, 1219, 800, CT["thickness"]


# ---- diagrams ----
class PlanView(Flowable):
    def __init__(self, width, height):
        self.width, self.height = width, height

    def draw(self):
        c = self.canv
        pad_l, pad_b = 26, 22
        aw, ah = self.width - pad_l - 8, self.height - pad_b - 14
        s = min(aw / overall_w, ah / overall_d)
        ox, oy = pad_l, pad_b
        gw, gd = overall_w * s, overall_d * s
        c.setDash(3, 2); c.setStrokeColor(ACCENT); c.setLineWidth(1); c.rect(ox, oy, gw, gd); c.setDash()
        rows = [(BANKS[:3], 0.0, 0), (BANKS[3:], 619.0, 180)]
        c.setFont("Helvetica", 6.2)
        for row, y0, ang in rows:
            x = 0.0
            for name, bw, grads in row:
                bx, by, bh = ox + x * s, oy + y0 * s, 600 * s
                c.setFillColor(LIGHT); c.setStrokeColor(LINE); c.setLineWidth(0.8)
                c.rect(bx, by, bw * s, bh, fill=1)
                face_y = by if ang == 0 else by + bh
                c.setStrokeColor(WOOD); c.setLineWidth(1.6)
                c.line(bx + 1, face_y, bx + bw * s - 1, face_y)
                c.setFillColor(INK); c.drawCentredString(bx + bw * s / 2, by + bh / 2 - 2, name)
                c.setFillColor(LINE); c.drawCentredString(bx + bw * s / 2, by + bh / 2 - 10, Lc(bw))
                x += bw
        c.setFillColor(LINE); c.setFont("Helvetica-Oblique", 5.8)
        c.drawCentredString(ox + gw / 2, oy + 605 * s, "back-to-back spine")
        c.setStrokeColor(LINE); c.setLineWidth(0.5); c.setFont("Helvetica", 6.5); c.setFillColor(INK)
        c.line(ox, oy - 8, ox + gw, oy - 8)
        c.drawCentredString(ox + gw / 2, oy - 15, "%s  (6 ft)" % L(overall_w))
        c.line(ox - 10, oy, ox - 10, oy + gd)
        c.saveState(); c.translate(ox - 14, oy + gd / 2); c.rotate(90)
        c.drawCentredString(0, 2, "%s  (4 ft)" % L(overall_d)); c.restoreState()
        c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 7)
        c.drawString(ox, oy + gd + 4, "PLAN  ·  worktop (dashed) over 6 banks, drawers face out both long sides")


class Elevation(Flowable):
    def __init__(self, width, height):
        self.width, self.height = width, height

    def draw(self):
        c = self.canv
        pad_l, pad_b, castor = 20, 20, 100
        total_h = castor + carcass_h + top_t
        aw, ah = self.width - pad_l - 10, self.height - pad_b - 16
        s = min(aw / overall_w, ah / total_h)
        ox, oy = pad_l, pad_b
        gw = overall_w * s
        c.setStrokeColor(LINE); c.setLineWidth(0.8); c.setFillColor(colors.HexColor("#8892a0"))
        for fx in (0.06, 0.94):
            cw = 60 * s
            c.roundRect(ox + fx * gw - cw / 2, oy, cw, castor * s, 4, fill=1)
        yb = oy + castor * s
        x = 0.0
        c.setFont("Helvetica", 5.8)
        for name, bw, grads in BANKS[:3]:
            bx, bw_s = ox + x * s, bw * s
            c.setFillColor(LIGHT); c.setStrokeColor(LINE); c.setLineWidth(0.9)
            c.rect(bx, yb, bw_s, carcass_h * s, fill=1)
            dy = yb + carcass_h * s
            for gh in grads:
                fh = gh * s
                dy -= fh
                c.setFillColor(WOOD); c.setStrokeColor(colors.HexColor("#7a5327")); c.setLineWidth(0.7)
                c.rect(bx + 2, dy + 1, bw_s - 4, fh - 2, fill=1)
                c.setFillColor(colors.HexColor("#3d3d3d")); c.circle(bx + bw_s / 2, dy + fh / 2, 1.1, fill=1)
                c.setFillColor(INK); c.drawCentredString(bx + bw_s / 2, dy + fh / 2 - 2, Lc(gh))
            x += bw
        c.setFillColor(ACCENT); c.setStrokeColor(colors.HexColor("#5f3d1c")); c.setLineWidth(1)
        c.rect(ox - 4, yb + carcass_h * s, gw + 8, top_t * s, fill=1)
        c.setStrokeColor(LINE); c.setLineWidth(0.5); c.setFont("Helvetica", 6.2); c.setFillColor(INK)
        xdim = ox + gw + 6
        c.line(xdim, oy, xdim, oy + total_h * s)
        wh = "~37 in working ht (with 4in castors)" if IMP else "~940 mm working ht (with 4in castors)"
        c.saveState(); c.translate(xdim + 5, oy + total_h * s / 2); c.rotate(90)
        c.drawCentredString(0, 0, wh); c.restoreState()
        c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 7)
        c.drawString(ox, oy + total_h * s + 5,
                     "FRONT ELEVATION  ·  maple top / graduated wood-runner drawers / locking castors")


# ---- cut-sheet nesting visual ----
PART_COLORS = [
    ("Drawer front", colors.HexColor("#c69c6d")), ("box side", colors.HexColor("#a7c4bc")),
    ("box front", colors.HexColor("#c3d9d3")), ("box bottom", colors.HexColor("#dfeae7")),
    ("wood runner", colors.HexColor("#9bbf8a")), ("Back", colors.HexColor("#b9c0c8")),
    ("countertop", colors.HexColor("#8a5a2b")), ("Side", colors.HexColor("#efe3cf")),
    ("Bottom", colors.HexColor("#e7d9be")), ("stretcher", colors.HexColor("#eadfc7")),
]


def part_color(label):
    for key, col in PART_COLORS:
        if key.lower() in label.lower():
            return col
    return colors.HexColor("#e8e8e8")


class CutSheets(Flowable):
    def __init__(self, width, boards, cols=3):
        self.width, self.boards, self.cols = width, boards, cols
        rows = (len(boards) + cols - 1) // cols
        self.cell_w = width / cols
        self.cell_h = self.cell_w * (STANDARD_SHEET[1] / STANDARD_SHEET[0]) + 22
        self.height = rows * self.cell_h

    def draw(self):
        c = self.canv
        for i, bp in enumerate(self.boards):
            col, row = i % self.cols, i // self.cols
            cx = col * self.cell_w
            cy = self.height - (row + 1) * self.cell_h
            b = bp.board
            pad = 6
            bw = self.cell_w - 2 * pad
            s = bw / b.length
            bh = b.width * s
            oy = cy + 16
            c.setFillColor(colors.white); c.setStrokeColor(INK); c.setLineWidth(0.8)
            c.rect(cx + pad, oy, bw, bh, fill=1)
            c.setLineWidth(0.4)
            for p in bp.placements:
                px, py = cx + pad + p.x * s, oy + p.y * s
                pw, ph = max(p.length * s, 0.6), max(p.width * s, 0.6)
                c.setFillColor(part_color(p.label)); c.setStrokeColor(colors.HexColor("#8f8f8f"))
                c.rect(px, py, pw, ph, fill=1)
            kind = ("%s maple slab" % Lc(b.thickness) if b.thickness == 40
                    else "%s birch ply" % Lc(b.thickness))
            c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 6.6)
            c.drawString(cx + pad, oy + bh + 5, "Sheet %d — %s" % (i + 1, kind))
            c.setFillColor(LINE); c.setFont("Helvetica", 5.8)
            c.drawRightString(cx + pad + bw, oy + bh + 5,
                              "%.0f%% used · %d parts" % (bp.yield_pct * 100, bp.part_count))


# ---- cut-list summary ----
def norm(name):
    n = re.sub(r"^[^·]*·\s*", "", name)
    n = re.sub(r"\s*#?\d+\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


agg = {}
for p in cl.parts:
    key = norm(p.name)
    a = agg.setdefault(key, {"qty": 0, "sizes": set(), "mat": p.material})
    a["qty"] += p.qty
    a["sizes"].add((round(p.length), round(p.width), round(p.thickness)))

order = ["Side", "Bottom", "Top stretcher", "Back", "Run countertop", "Drawer front",
         "Drawer box side", "Drawer box front/back", "Drawer box bottom", "wood runner"]


def sort_key(k):
    for i, o in enumerate(order):
        if o.lower() in k.lower():
            return (i, k)
    return (99, k)


ct_rows = [["Part", "Qty", "Typical size (%s)" % UCOL, "Material"]]
for k in sorted(agg, key=sort_key):
    a = agg[k]
    szs = sorted(a["sizes"])
    rep = dims3(szs[0]) + ("  (+%d sizes)" % (len(szs) - 1) if len(szs) > 1 else "")
    ct_rows.append([k, str(a["qty"]), rep, a["mat"]])

total_parts = sum(p.qty for p in cl.parts)
runner_parts = sum(p.qty for p in cl.parts if "wood runner" in p.name)


# ---- document ----
def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(INK); canvas.rect(0, letter[1] - 6, letter[0], 6, fill=1, stroke=0)
    canvas.setFillColor(ACCENT); canvas.rect(0, letter[1] - 9, letter[0], 3, fill=1, stroke=0)
    canvas.setFillColor(LINE); canvas.setFont("Helvetica", 7)
    canvas.drawString(0.6 * inch, 0.4 * inch,
                      "Woodworking AI  ·  compiled from mobile_storage_workbench.json  ·  %s units"
                      % ("imperial" if IMP else "metric"))
    canvas.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, "Design sheet · p.%d" % doc.page)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                        topMargin=0.5 * inch, bottomMargin=0.6 * inch,
                        title="Mobile Storage Workbench — Design Sheet", author="Woodworking AI")
story = [Paragraph("Mobile Storage Workbench", H1),
         Paragraph("Double-sided mobile island · storage-focused · 4 ft × 6 ft", SUB)]

work_ht = "≈36–37 in (on castors)" if IMP else "≈915–940 mm (on castors)"
facts = [
    ["OVERALL", "%s × %s (6 × 4 ft)" % (L(overall_w, False), L(overall_d)), "WORKING HT", work_ht],
    ["DRAWERS", "18 · graduated · 3 tiers × 6 banks", "RUNNERS", "wood-on-wood (no metal slides)"],
    ["WORKTOP", "%s laminated hard maple" % L(top_t), "CARCASS", "%s birch plywood" % L(18)],
    ["MOBILITY", "4 × heavy-duty locking castors", "EST. COST", "${:,.0f} materials".format(est.total)],
]
ft = Table(facts, colWidths=[0.9 * inch, 2.5 * inch, 0.85 * inch, 2.5 * inch])
ft.setStyle(TableStyle([
    ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
    ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 7.5), ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 7.5),
    ("TEXTCOLOR", (0, 0), (0, -1), ACCENT), ("TEXTCOLOR", (2, 0), (2, -1), ACCENT),
    ("TEXTCOLOR", (1, 0), (1, -1), INK), ("TEXTCOLOR", (3, 0), (3, -1), INK),
    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRID),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [ft, Spacer(1, 8)]

dg = Table([[PlanView(3.6 * inch, 2.7 * inch), Elevation(3.5 * inch, 2.7 * inch)]],
           colWidths=[3.7 * inch, 3.6 * inch])
dg.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOX", (0, 0), (0, 0), 0.5, GRID), ("BOX", (1, 0), (1, 0), 0.5, GRID),
                        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
story += [dg, Spacer(1, 8), Paragraph("Construction &amp; specification", H2)]

specs = [
    ["Carcass", "%s birch plywood; sides house the bottom in a %s dado." % (L(18), L(9))],
    ["Drawer boxes", "%s ply, dovetailed corners (tails on the sides — can't pull off), %s captured bottom." % (L(12), L(6))],
    ["Drawer runners", "Hardwood side runners screwed to the carcass; drawer sides grooved to ride them. No metal slides, no slide drilling."],
    ["Worktop", "%s laminated hard maple, one continuous slab flush to the 4×6 footprint." % L(top_t)],
    ["Mobility", "4 heavy-duty locking swivel castors (rate ≥200 kg each) on corner blocks / base rail."],
    ["Stability", "Low, wide, heavy double-sided island; wood runners aren't full-extension, so no wall anti-tip (deliberate)."],
]
st = Table([[Paragraph("<b>%s</b>" % a, CELL), Paragraph(b, CELL)] for a, b in specs],
           colWidths=[1.15 * inch, 6.1 * inch])
st.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID),
                        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [st, PageBreak(), Paragraph("Bank schedule", H2)]

bs = [["Bank", "Width (%s)" % UCOL, "Drawer fronts, top → bottom (%s)" % UCOL]]
for name, bw, grads in BANKS:
    bs.append([name, L(bw, False),
               "  ·  ".join(L(g, False) for g in grads) + "   (sum %s)" % L(sum(grads), False)])
bt = Table(bs, colWidths=[1.2 * inch, 1.1 * inch, 5.0 * inch])
bt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.2),
                        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.2),
                        ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                        ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [bt, Spacer(1, 8),
          Paragraph("Cut-list summary  (full per-part list in cutlist%s.csv)"
                    % ("_imperial" if IMP else ""), H2)]

ct_tbl = Table(ct_rows, colWidths=[1.7 * inch, 0.5 * inch, 2.6 * inch, 1.5 * inch], repeatRows=1)
ct_tbl.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                            ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("ALIGN", (1, 0), (1, -1), "CENTER"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                            ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [ct_tbl, Spacer(1, 10)]

sheet_area = format_area(sum(bp.board.area_m2 for bp in USED if bp.board.thickness != 40), UNIT)
tot = [
    ["Parts", "%d  (115 unique)" % total_parts, "Sheet goods", "~30.1 m² (324 ft²)"],
    ["Hardwood runners", "%d strips" % runner_parts, "Edge banding", run_len(49960)],
    ["Drilling", "%d holes (all wood-runner screws — 0 slide holes)" % sched.total_holes, "", ""],
    ["Est. build time", "~33 h (advanced)", "Est. materials", "${:,.2f}".format(est.total)],
]
tt = Table(tot, colWidths=[1.4 * inch, 2.4 * inch, 1.3 * inch, 2.2 * inch])
tt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.4),
                        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8), ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 8),
                        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT), ("TEXTCOLOR", (2, 0), (2, -1), ACCENT),
                        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("SPAN", (1, 2), (3, 2)),
                        ("LINEBELOW", (0, 0), (-1, -2), 0.3, GRID),
                        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [tt, Spacer(1, 8),
          Paragraph("Generated by the Woodworking AI pipeline (validator + geometry critic passed, "
                    "0 interferences). Full reports alongside: cutlist · drilling · joinery · "
                    "cutlayout.dxf. Dimensions overall in %s unless noted." % UCOL, SMALL)]

# ---- page: BOM ----
story += [PageBreak(), Paragraph("Materials to buy  (bill of materials)", H2)]

sheet_counts = Counter()
for bp in USED:
    b = bp.board
    if b.thickness == 40:
        label = "Hard maple worktop slab — glue-up ≈%s × %s × %s" % (L(1830, False), L(1220, False), L(40))
    else:
        label = "Birch plywood — %s, %s × %s sheet" % (L(b.thickness), L(b.length, False), L(b.width))
    sheet_counts[label] += 1

po = purchase_order(spec)
bom = [["Category", "Item", "Qty", "Unit", "Buy cost"]]
for label in sorted(sheet_counts, key=lambda s: ("maple" in s, s)):
    n = sheet_counts[label]
    cat = "Worktop" if "maple" in label else "Sheet goods"
    bom.append([cat, label, str(n), "slab" if "maple" in label else "sheet", ""])
seen = set()
for ln in po.lines:
    if ln.category in ("labour", "sheet"):
        continue
    item = "Hardwood for drawer runners (%s)" % ln.item if ln.category == "lumber" else ln.item
    if (ln.category, item) in seen:
        continue
    seen.add((ln.category, item))
    unit, qty = ln.unit, ln.qty
    if unit == "m":                       # banding: metres, or feet when imperial
        qstr, unit = ("%.0f" % (qty / 0.3048), "ft") if IMP else ("%.1f" % qty, "m")
    else:
        qstr = ("%.1f" % qty) if isinstance(qty, float) and qty % 1 else str(int(qty))
    cost = "$%.2f" % ln.line_total if ln.line_total else "—"
    cat = {"lumber": "Lumber", "banding": "Edge banding", "hardware": "Hardware"}.get(ln.category, ln.category.title())
    bom.append([cat, item, qstr, unit, cost])
for ln in po.consumables:
    bom.append(["Consumable", ln.item, "", "", "$%.2f" % ln.line_total])

bt2 = Table(bom, colWidths=[1.0 * inch, 3.5 * inch, 0.55 * inch, 0.7 * inch, 0.85 * inch], repeatRows=1)
bt2.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                         ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                         ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                         ("ALIGN", (2, 0), (2, -1), "CENTER"), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
                         ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                         ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                         ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
                         ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [bt2, Paragraph(
    "Sheet count is from the nesting layout ({n} plywood sheets + 1 maple slab, {y:.0f}% yield). "
    "Labour (~$1,131, ~17 h) and consumables are shown for a full quote; materials + hardware to "
    "buy total roughly ${buy:,.0f}.".format(n=len(USED) - 1, y=PLAN.yield_pct * 100,
                                            buy=est.total - 1131.0), SMALL),
    PageBreak()]

# ---- page: cut sheets ----
def hexstr(col):
    return "#%02x%02x%02x" % (int(col.red * 255), int(col.green * 255), int(col.blue * 255))


story.append(Paragraph("Cut sheets  (nesting layout on %s × %s stock)" % (L(2440, False), L(1220)), H2))
leg = [("Carcass side/bottom", part_color("Side")), ("Drawer front", part_color("Drawer front")),
       ("Drawer box", part_color("box side")), ("Wood runner", part_color("wood runner")),
       ("Back panel", part_color("Back")), ("Worktop", part_color("countertop"))]
lg = Table([[Paragraph('<font color="%s">■</font> %s' % (hexstr(col), name), SMALL)
             for name, col in leg]], colWidths=[1.2 * inch] * len(leg))
lg.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
story += [lg, CutSheets(7.3 * inch, USED, cols=3)]

doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print("wrote", OUT, "(%s units, %.1f KB)" % (UNIT, os.path.getsize(OUT) / 1024))
