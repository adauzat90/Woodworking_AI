"""Generate an IKEA-style assembly manual PDF for the Mobile Storage Workbench."""
import math, json, os, sys, re

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Flowable, PageBreak)

sys.path.insert(0, "src")
from woodworking_ai import spec_from_dict, generate_cutlist
from woodworking_ai.geometry import panel_layout

DATA = json.load(open("examples/mobile_storage_workbench.json", encoding="utf-8"))
SPEC = spec_from_dict(DATA)
CL = generate_cutlist(SPEC)
OUT = "examples/mobile_storage_workbench_docs/assembly_manual.pdf"

# one representative front bank (Front-L, 660 wide) for step diagrams
BANK_SPEC = spec_from_dict(DATA["runs"][0]["items"][0]["spec"])
BANK = panel_layout(BANK_SPEC)
ISLAND = panel_layout(SPEC)

INK = colors.HexColor("#1c2b36")
ACCENT = colors.HexColor("#8a5a2b")
WOOD = colors.HexColor("#d8bd92")
GHOST = colors.HexColor("#dfe3e7")
LIGHT = colors.HexColor("#f3ede4")
LINE = colors.HexColor("#6b7680")
GRID = colors.HexColor("#c9d1d9")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], textColor=INK, fontSize=26, leading=29,
                    alignment=TA_LEFT, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], textColor=ACCENT, fontSize=12, leading=15, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=ACCENT, fontSize=13, leading=15, spaceAfter=4)
BODY = ParagraphStyle("BODY", parent=styles["Normal"], textColor=INK, fontSize=9.5, leading=12.5)
SMALL = ParagraphStyle("SMALL", parent=styles["Normal"], textColor=LINE, fontSize=7.6, leading=9.5)
STEPN = ParagraphStyle("STEPN", parent=styles["Normal"], textColor=colors.white, fontSize=17,
                       leading=19, alignment=1)
STEPT = ParagraphStyle("STEPT", parent=styles["Normal"], textColor=INK, fontSize=10.5, leading=13)

C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def iso(x, y, z):
    return ((x - y) * C30, z - (x + y) * S30)


def _shade(base, f):
    return colors.Color(base.red * f + (1 - f), base.green * f + (1 - f), base.blue * f + (1 - f))


def _draw_box(c, box, ox, oy, sc, base, explode=(0, 0, 0)):
    cx, cy, cz = box.center
    sx, sy, sz = box.size
    cx += explode[0]; cy += explode[1]; cz += explode[2]
    hx, hy, hz = sx / 2, sy / 2, sz / 2

    def P(x, y, z):
        ix, iy = iso(x, y, z)
        return (ox + ix * sc, oy + iy * sc)

    faces = [
        ([P(cx + hx, cy - hy, cz - hz), P(cx + hx, cy + hy, cz - hz),
          P(cx + hx, cy + hy, cz + hz), P(cx + hx, cy - hy, cz + hz)], 0.62),
        ([P(cx - hx, cy - hy, cz - hz), P(cx + hx, cy - hy, cz - hz),
          P(cx + hx, cy - hy, cz + hz), P(cx - hx, cy - hy, cz + hz)], 0.82),
        ([P(cx - hx, cy - hy, cz + hz), P(cx + hx, cy - hy, cz + hz),
          P(cx + hx, cy + hy, cz + hz), P(cx - hx, cy + hy, cz + hz)], 1.0),
    ]
    c.setLineWidth(0.5); c.setStrokeColor(colors.HexColor("#4a5560"))
    for pts, f in faces:
        col = _shade(base, f)
        c.setFillColor(col)
        p = c.beginPath(); p.moveTo(*pts[0])
        for pt in pts[1:]:
            p.lineTo(*pt)
        p.close(); c.drawPath(p, fill=1, stroke=1)


def _fit(panels, w, h, pad=10):
    proj = []
    for b in panels:
        cx, cy, cz = b.center; sx, sy, sz = [s / 2 for s in b.size]
        for dx in (-sx, sx):
            for dy in (-sy, sy):
                for dz in (-sz, sz):
                    proj.append(iso(cx + dx, cy + dy, cz + dz))
    minx = min(p[0] for p in proj); maxx = max(p[0] for p in proj)
    miny = min(p[1] for p in proj); maxy = max(p[1] for p in proj)
    sc = min((w - 2 * pad) / (maxx - minx), (h - 2 * pad) / (maxy - miny))
    ox = w / 2 - (minx + maxx) / 2 * sc
    oy = h / 2 - (miny + maxy) / 2 * sc
    return sc, ox, oy


class Iso(Flowable):
    """Isometric diagram of a panel set, with optional explode + ghosted context."""
    def __init__(self, width, height, panels, base=WOOD, explode=None, ghost=None,
                 extra=None):
        self.width, self.height = width, height
        self.panels = panels
        self.base = base
        self.explode = explode or (lambda b: (0, 0, 0))
        self.ghost = ghost or []          # context parts drawn faint
        self.extra = extra or []          # (box, color) manual boxes (runners/castors)

    def draw(self):
        c = self.canv
        allp = list(self.ghost) + list(self.panels) + [b for b, _ in self.extra]
        sc, ox, oy = _fit(allp, self.width, self.height)
        for b in sorted(self.ghost, key=lambda b: b.center[0] - b.center[1] + b.center[2]):
            _draw_box(c, b, ox, oy, sc, GHOST)
        merged = [(b, self.base, self.explode(b)) for b in self.panels] + \
                 [(b, col, (0, 0, 0)) for b, col in self.extra]
        for b, col, ex in sorted(merged, key=lambda t: t[0].center[0] + t[2][0]
                                 - (t[0].center[1] + t[2][1]) + t[0].center[2] + t[2][2]):
            _draw_box(c, b, ox, oy, sc, col, ex)


# ---- panel subsets from the representative bank ----
def by(labelsub, panels=BANK):
    return [p for p in panels if labelsub in p.label]


carcass = [p for p in BANK if p.category in ("carcass", "back")]
box1 = by("Drawer 1 box")
front1 = [p for p in BANK if p.category == "front" and "Drawer front" in p.label][:3]


def carcass_explode(b):
    lab = b.label
    if "Side L" in lab: return (-260, 0, 0)
    if "Side R" in lab: return (260, 0, 0)
    if "Bottom" in lab: return (0, 0, -170)
    if "Back" in lab: return (0, 240, 40)
    if "Stretcher" in lab: return (0, 0, 200)
    return (0, 0, 0)


def box_explode(b):
    lab = b.label
    if "side L" in lab: return (-150, 0, 0)
    if "side R" in lab: return (150, 0, 0)
    if "front" in lab: return (0, -150, 0)
    if "back" in lab: return (0, 170, 0)
    if "bottom" in lab: return (0, 0, -120)
    return (0, 0, 0)


# runner strips: two per drawer, on the carcass side inner faces, at the drawer height
def runner_boxes():
    m = BANK_SPEC.material
    W = BANK_SPEC.width
    out = []

    class B:  # tiny stand-in with .center/.size/.category/.label
        def __init__(s, center, size, label="runner"):
            s.center, s.size, s.category, s.label = center, size, "runner", label
    interior = W / 2 - m.carcass
    # 3 drawers, put a runner pair at each drawer mid-height (approx)
    for i, z in enumerate((250, 470, 660)):
        for sgn in (-1, 1):
            out.append((B((sgn * (interior - 15), 300, z), (18, 520, 30)),
                        colors.HexColor("#9bbf8a")))
    return out


# ---- assembled bank (carcass + drawers in place) ----
def bank_assembled():
    keep = [p for p in BANK if p.category in ("carcass", "back", "front")
            or "box" in p.label]
    return keep


# ---- castor stand-ins under the island ----
def castor_boxes():
    class B:
        def __init__(s, center, size, label="castor"):
            s.center, s.size, s.category, s.label = center, size, "hardware", label
    out = []
    for fx in (120, 1709):
        for fy in (120, 1099):
            out.append((B((fx, fy, -55), (90, 90, 110)), colors.HexColor("#6a7480")))
    return out


# ---- worktop lifted off for the last step ----
def island_no_top():
    return [p for p in ISLAND if "Run countertop" not in p.label]


def worktop_lifted():
    out = []
    for p in ISLAND:
        if "Run countertop" in p.label:
            class B:
                def __init__(s, center, size, label, category):
                    s.center, s.size, s.label, s.category = center, size, label, category
            cx, cy, cz = p.center
            out.append(B((cx, cy, cz + 320), p.size, p.label, "counter"))
    return out


# ---- parts inventory ----
def norm(name):
    n = re.sub(r"^[^·]*·\s*", "", name)
    n = re.sub(r"\s*#?\d+\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


agg = {}
for p in CL.parts:
    k = norm(p.name)
    a = agg.setdefault(k, {"qty": 0, "sizes": set(), "ex": p})
    a["qty"] += p.qty
    a["sizes"].add((round(p.length), round(p.width), round(p.thickness)))
order = ["Side", "Bottom", "Top stretcher", "Back", "Run countertop", "Drawer front",
         "Drawer box side", "Drawer box front/back", "Drawer box bottom", "wood runner"]


def okey(k):
    for i, o in enumerate(order):
        if o.lower() in k.lower():
            return (i, k)
    return (99, k)


PART_LETTERS = {}
for i, k in enumerate(sorted(agg, key=okey)):
    PART_LETTERS[k] = chr(ord("A") + i)


class PartThumb(Flowable):
    def __init__(self, size, ex):
        self.width = self.height = size
        self.ex = ex

    def draw(self):
        c = self.canv
        p = self.ex

        class B:
            pass
        b = B(); b.center = (0, 0, 0)
        L, W, T = p.length, p.width, p.thickness
        b.size = (L, W, T)  # lay flat: length X, width Y, thickness Z
        b.category = "x"; b.label = p.name
        sc, ox, oy = _fit([b], self.width, self.height, pad=6)
        _draw_box(c, b, ox, oy, sc, WOOD)


# ---- build document ----
def cover_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(INK); canvas.rect(0, letter[1] - 7, letter[0], 7, fill=1, stroke=0)
    canvas.setFillColor(ACCENT); canvas.rect(0, letter[1] - 10, letter[0], 3, fill=1, stroke=0)
    canvas.setFillColor(LINE); canvas.setFont("Helvetica", 7)
    canvas.drawString(0.6 * inch, 0.4 * inch, "Woodworking AI  ·  Mobile Storage Workbench  ·  assembly manual")
    canvas.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, "p.%d" % doc.page)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                        topMargin=0.5 * inch, bottomMargin=0.6 * inch,
                        title="Mobile Storage Workbench — Assembly Manual", author="Woodworking AI")
story = []

# ---- cover ----
story += [Paragraph("Assembly manual", H1),
          Paragraph("Mobile Storage Workbench · double-sided island · 18 drawers", SUB),
          Iso(7.2 * inch, 3.7 * inch, ISLAND, base=WOOD), Spacer(1, 6)]
before = [
    ["Time", "~33 h over several sessions", "People", "2 (worktop + island are heavy)"],
    ["Level", "Advanced — dovetails + wood runners", "Glue", "PVA; have wet rag + clamps ready"],
    ["Tools", "Table saw, router (straight + dovetail), drill, chisels, clamps, square, mallet", "", ""],
]
bt = Table(before, colWidths=[0.7 * inch, 3.0 * inch, 0.7 * inch, 2.8 * inch])
bt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
                        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8), ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 8),
                        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT), ("TEXTCOLOR", (2, 0), (2, -1), ACCENT),
                        ("SPAN", (1, 2), (3, 2)), ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
                        ("LINEBELOW", (0, 0), (-1, -2), 0.3, GRID),
                        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [bt, Paragraph("Read every step before you start. Dry-fit (no glue) each sub-assembly "
                        "first; glue only once it goes together square.", SMALL), PageBreak()]

# ---- parts inventory ----
story += [Paragraph("Parts  (cut from the sheet layout — see the design sheet)", H2)]
prow = []
cells = []
for k in sorted(agg, key=okey):
    a = agg[k]
    szs = sorted(a["sizes"])[0]
    dim = "%d×%d×%d" % szs
    letter_id = PART_LETTERS[k]
    tbl = Table([[PartThumb(0.62 * inch, a["ex"])],
                 [Paragraph("<b>%s</b> ×%d" % (letter_id, a["qty"]), SMALL)],
                 [Paragraph("%s" % k, SMALL)],
                 [Paragraph("%s mm" % dim, SMALL)]],
                colWidths=[1.15 * inch], rowHeights=[0.62 * inch, 0.16 * inch, 0.22 * inch, 0.15 * inch])
    tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                             ("BOX", (0, 0), (-1, -1), 0.4, GRID), ("BACKGROUND", (0, 0), (-1, 0), colors.white)]))
    cells.append(tbl)
grid = [cells[i:i + 6] for i in range(0, len(cells), 6)]
for r in grid:
    r += [""] * (6 - len(r))
gt = Table(grid, colWidths=[1.2 * inch] * 6)
gt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
story += [gt]

# hardware
hw = {}
for h in CL.hardware:
    hw[h.name] = hw.get(h.name, 0) + h.qty
hw_rows = [["Hardware / consumable", "Qty / note"]]
hw_pref = [("Drawer pull", "18 — one per drawer"), ("Wood runner", "36 hardwood strips (2 per drawer)"),
           ("Assembly screw", "~24 — carcass"), ("Back panel screw", "~60"),
           ("Locking castor", "4 — heavy-duty, ≥200 kg each (buy separately)"),
           ("Edge banding", "~50 m to match shown edges"), ("Wood glue (PVA)", "~1 L"),
           ("Sandpaper", "120–220 grit"), ("Finish", "hard-wax oil / poly for the maple top")]
hw_tbl = Table([["Hardware & consumables", ""]] + [[a, b] for a, b in hw_pref],
               colWidths=[2.6 * inch, 4.6 * inch])
hw_tbl.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.6),
                            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                            ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("SPAN", (0, 0), (-1, 0)),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                            ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
story += [Spacer(1, 4), hw_tbl, PageBreak()]


# ---- steps ----
def step_block(n, title, text, iso_flowable, parts="", tools=""):
    num = Table([[Paragraph(str(n), STEPN)]], colWidths=[0.34 * inch], rowHeights=[0.34 * inch])
    num.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    head = Table([[num, Paragraph("<b>%s</b>" % title, STEPT)]], colWidths=[0.44 * inch, 6.8 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    bits = [head, Spacer(1, 2), iso_flowable, Spacer(1, 2), Paragraph(text, BODY)]
    if parts:
        bits.append(Paragraph("<b>Parts:</b> %s" % parts, SMALL))
    if tools:
        bits.append(Paragraph("<b>Hardware/tools:</b> %s" % tools, SMALL))
    return bits


def PL(*keys):
    return "  ".join("%s" % PART_LETTERS[k] for k in keys if k in PART_LETTERS)


D = 3.15 * inch
steps = [
    (1, "Build a drawer-bank carcass  (repeat ×6)",
     "Dry-fit two sides, the dadoed bottom and the two top stretchers into a box; the back "
     "sits in the rear rabbet. Check it is square, then glue and clamp. Groove/dado already cut.",
     Iso(D, 2.5 * inch, carcass, explode=carcass_explode),
     PL("Side", "Bottom", "Top stretcher", "Back"), "PVA glue, bar clamps, square"),
    (2, "Fit the hardwood drawer runners",
     "Screw a hardwood runner to each carcass side at every drawer level (two per drawer). "
     "The grooved drawer sides will ride on these — no metal slides.",
     Iso(D, 2.5 * inch, carcass, base=GHOST, extra=runner_boxes()),
     PL("wood runner"), "2 screws per runner"),
    (3, "Build a dovetailed drawer box  (repeat ×18)",
     "Cut the drawer box: dovetail the corners (tails on the SIDES so the front can't pull off). "
     "Plough a groove in all four walls for the bottom.",
     Iso(D, 2.5 * inch, box1, explode=box_explode),
     PL("Drawer box side", "Drawer box front/back", "Drawer box bottom"), "PVA glue, dovetail jig"),
    (4, "Fit the bottom & attach the drawer front",
     "Slide the plywood bottom into its grooves as you glue up the box (don't glue the bottom — "
     "let it float). Screw the graduated front to the box from inside; fit the pull.",
     Iso(D, 2.5 * inch, box1 + front1,
         explode=lambda b: (0, -220, 0) if b.category == "front" else (0, 0, 0)),
     PL("Drawer front"), "Drawer pull, 4×16 screws"),
    (5, "Slide the drawers into the bank",
     "Groove in each drawer side drops onto its runner. Test the action; wax the runners so they "
     "glide. Repeat for all three drawers, then all six banks.",
     Iso(D, 2.6 * inch, bank_assembled()), "", "paste wax"),
    (6, "Join the two rows & fit the castors",
     "Stand the six banks in two rows of three, backs together, and bolt the rows into one island. "
     "Screw a locking castor to each of the four bottom corners (on blocks / a base rail).",
     Iso(D, 2.7 * inch, island_no_top(), extra=castor_boxes()),
     "", "4 locking castors, connector bolts"),
    (7, "Fasten the maple worktop",
     "Lower the laminated maple top onto the island, flush to the footprint, and fix it down "
     "from inside the top stretchers. Finish the top with hard-wax oil or poly.",
     Iso(D, 2.7 * inch, island_no_top(), extra=[(b, colors.HexColor("#8a5a2b")) for b in worktop_lifted()]),
     PL("Run countertop"), "fasteners into stretchers, finish"),
]

for i in range(0, len(steps), 2):
    for n, title, text, iso_fl, parts, tools in steps[i:i + 2]:
        story += step_block(n, title, text, iso_fl, parts, tools)
        story += [Spacer(1, 10)]
    story += [PageBreak()]

# drop the trailing pagebreak
if story and isinstance(story[-1], PageBreak):
    story.pop()

doc.build(story, onFirstPage=cover_bg, onLaterPages=cover_bg)
print("wrote", OUT, "(%.1f KB)" % (os.path.getsize(OUT) / 1024))
