# Furniture & Casework Design Principles

Research foundation for the Woodworking AI compiler. This document explains how
furniture and cabinets are *correctly* designed; the companion
[`validation-rules.md`](./validation-rules.md) turns these principles into
machine-checkable rules.

Units are US customary (inches) with metric where standards use it.

---

## 1. Ergonomics & standard dimensions

Furniture must fit the human body and its tasks. These dimensions are
near-universal conventions; deviating from them produces furniture that is
technically sound but uncomfortable or unusable.

### 1.1 Seating and work surfaces

| Element | Standard | Notes |
|---|---|---|
| Dining table height | 28–30 in (≈30 in typical) | Top of surface to floor |
| Counter-height table | 34–36 in | Pairs with 24–27 in stools |
| Bar-height table | 40–42 in | Pairs with 28–33 in stools |
| Dining chair seat height | 18–20 in | Floor to top of seat |
| Desk height (fixed) | 28.3–29.5 in (72–75 cm) | Designed around standard chairs |
| Seat-to-underside clearance | 10–12 in | Thigh/knee room under the apron |

**Key ergonomic coupling:** seat height and table height are not independent —
there must be ~10–12 in between the seat and the underside of the top. A
30 in table with a 20 in chair leaves 10 in of thigh clearance (good); a 30 in
table with a counter stool does not work. The compiler should check the
*difference*, not just absolute heights.

**Desk/keyboard ergonomics:** elbows ~90°, wrists straight, monitor at roughly
arm's length (50–70 cm). Desk depth ≥ ~80 cm (≈31 in) supports correct monitor
distance.

### 1.2 Kitchen cabinet dimensions (industry standard)

Base cabinets:
- Depth: **24 in**; Height: **34.5 in** (+1.5 in countertop = **36 in** finished)
- Toe kick: **3.5–4.5 in tall**, recessed (KCMA minimum: 2 in deep × 3 in high)
- Widths: **9–48 in in 3-in increments**

Wall cabinets:
- Depth: **12 in**; Heights: 12, 15, 18, 21, 24, **30, 36, 42 in**

Tall/pantry: 84–96 in. Vanity: ~21 in deep, 31.5–34.5 in high.

These modular increments matter because cabinets are assembled into runs;
non-standard widths break the 3-in grid and complicate fillers/appliances.

### 1.3 Shelving & storage

- Bookshelf vertical spacing: ~8–12 in typical; adjustable preferred.
- A fully loaded bookshelf carries **20–40 lb per running foot** (use ~35 lb/ft
  for library-grade) — this is the design load for sag analysis (§3.3).

---

## 2. Proportion & aesthetics

Function-correct furniture can still look wrong. The dominant heuristic is the
**Golden Ratio (≈1.618:1)** for primary rectangles (top length:width, case
height:width, drawer bank divisions). The **Rule of Thirds** is a looser
compositional aid (it is *not* the same as the golden ratio). These are
**advisory (INFO)** checks — pleasing proportions, not safety.

Practical uses: tabletop length:width, door/drawer face subdivisions, leg
thickness relative to overall mass, plinth/cornice heights.

---

## 3. Structural integrity

This is where most hard (ERROR-level) failures live.

### 3.1 Racking (lateral/shear stability)

A rectangular frame has **no inherent resistance to lateral force** — pushed
sideways, the corners distort into a parallelogram (racking). Resistance comes
from **triangulation and rigid corner joints**:

- **Aprons** (panels tying the legs to the top) are the primary anti-rack
  element on tables/desks; corner blocks reinforce them.
- **Stretchers** (horizontal ties low between legs) add rigidity for tall or
  long bases; aprons + lower stretchers give a large racking-resistance gain.
- **Joint choice drives racking resistance:** mortise-and-tenon ≫ dowels ≫
  pocket screws. Pocket holes alone are **not adequate** for a dining-table
  leg-to-apron connection (very low racking resistance). M&T shear strength is
  cited at ~5× nailed joints.

Rule of thumb the compiler can encode: any table/desk/chair base needs *either*
an apron or stretchers (preferably engaging the legs with M&T-class joints);
flag leg-to-rail connections that rely on pocket screws or butt joints alone.

### 3.2 Joint selection by load (strength hierarchy)

| Joint | Relative strength | Best for | Weakness |
|---|---|---|---|
| Mortise & tenon | Highest (stronger than the wood) | Chair/table legs↔rails, doors, face frames | Skill/time |
| Dovetail | Very high, directional | Drawer corners (resists pull-open) | Hand skill |
| Box/finger joint | High; strongest table-saw joint | Boxes, drawers | Visible end grain |
| Dado / rabbet | Good in shear/compression | Shelves into sides, case backs | Needs glue/fastener for tension |
| Dowel | Moderate | Casework, alignment + some strength | Less racking resistance than M&T |
| Biscuit | Low structural / alignment aid | Panel glue-up flushing | Adds little strength |
| Pocket screw | Moderate, screw-dependent | Face frames, fast cabinets | Loosens with seasonal movement; poor racking |
| Butt joint | Lowest | Non-structural, low-stress | Almost no tension/shear resistance |

**Directionality matters:** dovetails resist pulling in one direction only —
orient them so the load (e.g. a drawer being yanked open) is resisted by the
interlock.

### 3.3 Shelf sag / deflection

Shelves are beams. Two acceptance criteria:

- **Engineering limit:** max deflection = **span / 360** (e.g. 36 in → 0.10 in).
- **Visual limit (stricter):** the eye notices **1/32 in (0.03 in) per running
  foot**, i.e. ~3/32 in over a 3 ft shelf. Many woodworkers target this.

Drivers of sag: span (cubed — dominant), load, thickness (cubed), and material
stiffness (Young's modulus E):

- Maple ≈ 1.83M psi, Oak ≈ 1.8M psi (best common shelf woods)
- Plywood ≈ 1.5M psi (good budget option)

Practical span guidance for **¾ in plywood**: 24–30 in at moderate load
(20–30 lb/ft²); limit to 18–24 in or add center support for heavy loads. The
compiler should compute deflection from span, thickness, E, and load and compare
to both limits (this is the "Sagulator" calculation).

### 3.4 Stability / tip-over (regulated)

For tall storage furniture, tip-over is a **mandatory safety** concern in the US:

- **ASTM F2057-23** (Clothing Storage Units) is CPSC-mandatory under the STURDY
  Act (effective Sept 2023). Scope: freestanding units **≥ 27 in tall**,
  **≥ 30 lb**, **> 3.2 ft³** enclosed storage.
- Tests include unloaded stability and a loaded test simulating a ~5-year-old
  climbing (e.g. open drawers + applied load).
- Designs should support **anti-tip restraints** and mark wall-attachment
  points.

Design implications: deep enough base / center of gravity low enough that the
unit doesn't tip when a top drawer is loaded and opened; provide a hardware
point for wall anchoring. The compiler can flag tall narrow casework and require
an anti-tip provision.

### 3.5 Casework performance standard (cabinets)

**ANSI/KCMA A161.1** is the recognized performance + construction standard for
kitchen/vanity cabinets. Highlights the compiler can mirror:

- Cabinets must be **fully enclosed** (wall: back/bottom/sides/top; base:
  back/bottom/sides).
- Toe space ≥ **2 in deep × 3 in high**.
- Performance tests: doors/drawers cycled **25,000×**; wall cabinets loaded to
  **600 lb**; shelves long-term load test; finish chemical/stain resistance.

---

## 4. Material behavior

Wood is anisotropic and hygroscopic; ignoring this cracks furniture even when
the structure is sound. These are among the most important compiler checks
because they are invisible at assembly time and fail months later.

### 4.1 Wood movement (seasonal expansion/contraction)

- Wood moves almost entirely **across the grain**, negligibly along it.
- Seasonal moisture content swings ~6%/year; **~4% MC change → ~1% dimensional
  change across the grain**.
- **Rules of thumb for solid wood:** allow **¼ in per 12 in** of width for
  flatsawn; **⅛ in per 12 in** for quartersawn (quartersawn moves ~half as
  much). So a 12 in flatsawn top can move ~⅛–¼ in seasonally.

**Design strategies the compiler should require/recognize:**
- **Frame-and-panel:** solid panels must **float** in their grooves with
  expansion gaps; never glued in.
- **Breadboard ends:** elongated/slotted peg holes so the end can slide.
- **Tabletop attachment:** figure-8 fasteners, Z-clips, or slotted cleats —
  never a rigid screw grid across the width.
- Account for grain cut (flat vs. quarter) when sizing the allowance.

### 4.2 Grain direction & glue joints

- **Long-grain to long-grain glue joints are strong** (stronger than the wood);
  **end-grain glue joints are weak** — glue doesn't adhere to the cell ends.
  Non-mechanical joints must be designed long-grain to long-grain.
- **Never rigidly cross-grain glue** (e.g. gluing a solid breadboard fully
  across a top, or a wide solid panel locked at both ends): the two parts move
  differently and the panel splits. This is a hard ERROR for solid wood.
- Orient grain **along the long/structural dimension** of parts (legs, rails,
  shelves). To get a wide panel, **glue up multiple narrower boards** rather
  than running grain crosswise.
- Keep grain orientation consistent in glue-ups (don't mix flatsawn and
  quartersawn edges arbitrarily) to avoid differential movement and cracking.

### 4.3 Material stock standards (buildability)

The compiler should validate part thicknesses/sizes against real stock so a
design is actually buildable.

**Sheet goods (plywood) — nominal vs. actual thickness:**

| Nominal | Actual | | Nominal | Actual |
|---|---|---|---|---|
| ¾ in | 23/32 in | | ⅜ in | 11/32 in |
| ⅝ in | 19/32 in | | ¼ in | ¼ in |
| ½ in | 15/32 in | | ⅛ in | ⅛ in |

Sheet sizes: **4×8 ft** standard; also 5×5 ft, 2×4 ft, project panels.
Sanding can remove up to 1/32 in — design joinery (dados) to **actual**, not
nominal, thickness.

**Hardwood lumber — quarter system (rough → surfaced):**

| Nominal | Rough | ≈ Surfaced (S2S) |
|---|---|---|
| 4/4 | 1 in | ~13/16 in |
| 5/4 | 1¼ in | ~1-1/16 in |
| 6/4 | 1½ in | ~1-5/16 in |
| 8/4 | 2 in | ~1-13/16 in |

Expect ~3/16 in loss per face when surfacing. The compiler should warn if a
design assumes a finished thickness that requires more material than the chosen
rough stock provides.

---

## 5. Hardware & clearances (manufacturability)

A design that ignores hardware geometry won't assemble.

### 5.1 Drawers & slides

- **Side-mount slides need exactly ½ in clearance per side** (spec:
  +1/32 / −0 in). Drawer box width = opening width − 1 in. The compiler must
  enforce this gap or the drawer won't fit / won't run.
- Extension types: **¾-extension** (~75%), **full extension**, **over-travel**
  (drawer clears the case). Choose by access need; full/over-travel needs the
  slide length to match the box depth.
- **Inset vs. overlay** changes usable drawer depth (inset drawers are shorter).

### 5.2 Doors

- **Overlay vs. inset** construction; consistent **reveal/gap** between doors
  and around openings (typ. ~1/16–1/8 in inset reveal; overlay sized so doors
  don't collide). Hinges (e.g. 35 mm cup for Euro/concealed) impose bore
  geometry and minimum stile widths.

### 5.3 Manufacturing grid

Cabinet runs use the **32 mm system** (frameless) and 3-in width increments
(see §1.2). Hole patterns, hinge plates, and slide mounts assume this grid;
off-grid parts force custom hardware.

---

## 6. Summary: what "well-designed" means to the compiler

A design passes when it is simultaneously:

1. **Ergonomic** — dimensions match human use and the coupled-dimension rules.
2. **Proportionate** — primary rectangles are visually balanced (advisory).
3. **Structurally sound** — joints suit their loads; bases resist racking;
   shelves don't sag past limits; tall units don't tip.
4. **Material-correct** — wood movement accommodated; grain oriented and glued
   correctly; never cross-grain-locked.
5. **Buildable** — parts map to real stock thicknesses/sheet sizes; hardware
   clearances and assembly grid respected.
6. **Standards-compliant** — meets the relevant ANSI/KCMA, ASTM/CPSC, BIFMA, or
   AWI requirement for its furniture class.

---

## Sources

- [Table and chair height guidelines — Benham's Blog](https://www.briansbenham.com/table-and-chair-height-guidelines/) · [Standard table heights](https://www.briansbenham.com/standard-table-heights/)
- [Ergonomics and Design: A Reference Guide (Oregon State EHS)](https://ehs.oregonstate.edu/sites/ehs.oregonstate.edu/files/pdf/ergo/ergonomicsanddesignreferenceguidewhitepaper.pdf)
- [Office furniture dimensions guide — Kavela](https://kavela.furniture/en/office-furniture-dimensions-guide/)
- [Standard kitchen cabinet sizes — CabinetSelect](https://cabinetselect.com/standard-kitchen-cabinet-sizes/) · [Cabinet dimensions — Unfinished Kitchen Cabinets](https://www.unfinished-kitchen-cabinets.net/blog/kitchen-cabinet-dimensions)
- [ANSI/KCMA A161.1-2022 standard (PDF)](https://kcma.org/sites/default/files/2024-08/KCMA%20A161.1%202022%20High%20Res.pdf) · [KCMA quality certification](https://kcma.org/certifications/kcma-quality-cabinet-certification) · [The strength behind ANSI/KCMA A161.1 — Woodworking Network](https://www.woodworkingnetwork.com/cabinets/strength-behind-certified-cabinetry-ansikcma-a1611)
- [12 essential wood joints — WWGOA](https://www.wwgoa.com/post/best-woodworking-joints) · [9 types of wood joints — Kreg](https://learn.kregtool.com/learn/joining-wood/) · [Strongest wood joints — Knapp](https://knappconnectors.com/blog/how-to-resources/what-are-the-strongest-types-of-wood-joints/) · [Wood joint strength testing — Woodgears](https://woodgears.ca/joint_strength/)
- [Table aprons vs stretchers vs leg — FineWoodworking](https://www.finewoodworking.com/forum/table-aprons-vs-stretchers-vs-leg-diameter-for-strength-and-wobble) · [When does a table need stretchers — FineWoodworking](https://www.finewoodworking.com/forum/when-does-a-table-need-stretchers) · [Structural design principles — Univ. Melbourne Machine Workshop](https://ms-kb.msd.unimelb.edu.au/machine-workshop/making/step-by-step/designing/designing-for-making/structural-design-principles)
- [The Sagulator — WoodBin](https://woodbin.com/calcs/sagulator/) · [AWI shelf span calculator](https://awinet.org/tools/shelf-span/) · [Shelf span calculator](https://woodworking-calculators.com/shelf-span-calculator/)
- [Wood movement — Flowyline](https://flowyline.com/blogs/for-diy-ers/wood-movement) · [Rules of thumb for wood movement — FineWoodworking](https://www.finewoodworking.com/forum/rules-of-thumb-for-wood-movement) · [Understanding grain direction and wood movement — WoodnBits](https://woodnbits.com/craftsmanship/understanding-grain-direction-and-wood-movement/) · [Wood movement — Workshop Companion](https://workshopcompanion.com/know-how/design/nature-of-wood/wood-movement.html)
- [End grain glue joints — Sawmill Creek](https://sawmillcreek.org/threads/end-grain-glue-joints-are-stronger.293547/) · [Glue and end grain — FineWoodworking](https://www.finewoodworking.com/forum/glue-and-end-grain) · [What is grain direction — EZNESTING](https://eznesting.com/blog/what-is-grain-direction)
- [Plywood nominal vs actual thickness — Inch Calculator](https://www.inchcalculator.com/actual-plywood-thickness-size/) · [Lumber dimensions guide — Home Stratosphere](https://www.homestratosphere.com/lumber-dimensions/)
- [Choosing drawer slides — Rockler](https://www.rockler.com/learn/choosing-drawer-slide) · [How to choose the right drawer slide — Woodworking Network](https://www.woodworkingnetwork.com/best-practices-guide/components-hardware-assembly/how-choose-right-drawer-slide)
- [ASTM F2057-23 tip-over standard — CPSC](https://www.cpsc.gov/Newsroom/News-Releases/2023/CPSC-Adopts-Final-Consumer-Product-Safety-Standard-to-Prevent-Tip-overs-of-Dressers-and-Other-Clothing-Storage-Units) · [CPSC adopts ASTM F2057-23 — UL Solutions](https://www.ul.com/news/cpsc-adopts-astm-f2057-23-prevent-furniture-tip-overs) · [Storage furniture stability testing — Eurofins](https://www.eurofins.com/toys-hardlines/resources/articles/furniture-testing-101-storage-furniture-stability-testing-for-safer-homes-and-stronger-brands/)
- [Golden ratio in furniture design — Krovel](https://www.krovelmade.com/blogs/shop-notes/the-golden-ratio-in-furniture-design) · [Woodworking golden ratio — Woodwork Handbook](https://woodworkhandbook.com/woodworking-golden-ratio/)
