# Implementation Plan — closing the gap from "impressive demo" to "shop product"

This plan turns the woodworker's review into concrete engineering work. It is
written **against the merged `main` line** (post PR #6), so it credits what is
already done and only specifies what is genuinely missing.

## What the merge already delivered (do not re-build)

The build-manual work that merged in PR #6 retired most of the "paperwork" gaps:

- **5-piece doors** — `door_style` (slab | shaker | raised_panel | cope_stick),
  built in `cutlist._add_door_parts` (stiles/rails/floating panel).
- **Orderable hardware catalog** with real Blum/Hettich/Grass SKUs + bore
  geometry (`hardware.py`).
- **Finishing schedule** — grit sequence, coats, litres, finishable area
  (`finishing.py`).
- **Joinery setup sheets** — cut width/depth/reference per part (`joinery.py`).
- **Assembly steps** — sub-assembly decomposition + ordered steps
  (`assembly_steps.py`).
- **Printable build package (PDF)** — cover, drawings, BOM, nesting, drilling,
  joinery, assembly, all cross-referenced by **shared part IDs**
  (`report.py`, `cutlist.assign_ids`).
- **Shop profiles** — house defaults + hardware brand + pricing (`profile.py`).
- **Room/wall fitting** — filler sizing, scribe allowances (`room.py`).
- **Accessories** — countertop, filler, end panel, molding, and an `appliance`
  entry whose **cutout fit is validated** (`accessories.py`).
- **Drilling schedule** with real hole coordinates `Hole(u, v, dia, depth)`
  (`drilling.py`).
- **Spec diffing** for revisions (`diffing.py`).
- **Material make-up** — form/species on the cut list (`materials.py`, `Stock`).

The two structural gaps from the review remain, plus a handful of shop-floor
realities. Those are what this plan implements.

---

## The remaining gaps (what this plan covers)

| # | Gap | Today | Target |
|---|-----|-------|--------|
| A | **Geometry is a placement diagram, not a machined model** | `builder.py` places butt-jointed slabs; `dxf.py` emits outlines + text only; the drilling `Hole` coordinates are never drawn or cut | Bores + joinery appear in the DXF and (optionally) the STEP; the Critic can verify them |
| B | **It designs boxes, not kitchens** | `appliance` only validates a cutout *fits*; the counter is a full rectangle; no void/range-gap; no appliance schedule | Real appliance model: counter cutouts subtracted, dishwasher/range voids in a run, an appliance schedule in the package |
| C | **Hardware/material not snapped to purchasable reality** | `slide_length` is validated only if supplied; edge-banding is one rough running line; nominal vs actual sheet thickness not modeled | Box depth auto-snaps to a real slide length; per-edge banding; real stock thicknesses |
| D | **A design tool, not a shop product** | Quote exists; `diffing.py` exists but isn't surfaced; no purchase order; no job/customer/revision model | Supplier-grouped purchase order; revisions surfaced in the web app; a customer proposal view |

---

## Workstream A — Make the geometry as honest as the paperwork

**Goal:** the machining intent that already exists as *numbers* (drilling
schedule, joinery setup sheet) becomes *geometry* a shop can cut from, and the
Critic can verify it.

### A1 — Emit bores into the nested DXF and per-part drawings  ★ quick win

The drilling schedule already produces every hole with `(u, v, dia, depth)` per
part. The DXF nest draws only outlines. Wire the holes in.

- **Files:** `dxf.py`, `drilling.py`, `exporters.py`.
- **Tasks:**
  - Add `_circle(cx, cy, r, layer)` to `dxf.py` (DXF `CIRCLE` entity).
  - In `export_cutlayout_dxf`, look up each placed part's `Hole`s by part ID
    (`drilling_schedule(spec)`), transform `(u, v)` into the part's nested
    frame (respecting rotation), and draw each on a `BORE` layer, with a small
    text tag of the diameter for through vs. stopped (e.g. `⌀5` / `⌀35×12.5`).
  - Add layers `BORE`, `DADO`, `RABBET` so a CAM post can map them to tools.
  - Reuse the same projection in `drawings.projected_views` so per-part shop
    drawings show the bores too.
- **Data model:** none — purely emits existing data.
- **Tests (`tests/test_export_cad.py`, new `tests/test_dxf_bores.py`):**
  - A door leaf's DXF contains 2 hinge-cup circles at `dia=35` placed at the
    catalog inset; a side panel contains the shelf-pin rows; counts match
    `drilling_schedule(spec).total_holes`.
  - Bores land inside the part outline (no hole off the panel).
- **Acceptance:** the cut-layout DXF a shop opens shows the line-boring and
  hinge cups on the correct parts, keyed to the cut-list IDs.
- **Effort:** S. **Risk:** low. **Depends on:** nothing. **Do first.**

### A2 — Cut joinery + bores into the build123d model (real STEP)

Make the B-Rep honest: subtract dados, rabbets, grooves, hinge cups, shelf-pin
and slide-pilot holes from the solids, so the STEP is machine-meaningful.

- **Files:** `builder.py` (the compiler), driven by `joinery.joinery_schedule`
  and `drilling.drilling_schedule`; `geometry.py` for placement frames.
- **Tasks:**
  - Add a `_apply_joinery(panel_solid, ops, frame)` helper that, for each
    `JoineryOp` on a part, boolean-subtracts a box (dado/rabbet/groove) at the
    op's width/depth/reference.
  - Add `_apply_bores(panel_solid, holes, frame)` that subtracts cylinders for
    each `Hole` (through vs. stopped by `depth`).
  - Keep it **opt-in and degrade-safe**: a `joinery_geometry: bool` build flag
    (default off for speed); when off, behavior is today's slabs. Booleans are
    OCC-expensive, so guard with a per-part try/except that logs and falls back
    to the slab on failure (never crash an export).
  - Single source of truth preserved: the ops/holes come from the same
    `joinery_schedule`/`drilling_schedule` the paperwork uses.
- **Tests (`tests/test_joinery_geometry.py`):**
  - Built side panel volume = slab volume − Σ(dado volumes) within tolerance.
  - A hinge door has two cylindrical pockets of `dia≈35`, `depth≈12.5`.
  - With the flag off, geometry is byte-for-byte today's output (regression).
- **Acceptance:** `woodai build spec.json --step --joinery` produces a STEP
  whose panels carry their dados and bores.
- **Effort:** L. **Risk:** med (OCC boolean robustness/perf). **Depends on:** A1
  (shared hole→frame transform). **Behind a flag** so it never blocks shipping.

### A3 — Critic verifies joinery feasibility (not just envelopes)

Once joinery is modeled, the Critic should catch joinery-level failures the
slab model structurally cannot.

- **Files:** `agents/critic.py`, with analytic checks also added to
  `validator.py` (so they run with no CAD).
- **Tasks (analytic, CAD-free):**
  - **Hinge-cup blow-through:** `door_thickness − HINGE_CUP_DEPTH < backing_min`
    → error (extend the existing `HINGE_MIN_DOOR_BACKING` check to depth).
  - **Dado-to-edge:** a housed joint whose center sits < `1×stock` from a panel
    end → warning (blow-out / weak short-grain).
  - **Slide-pilot vs shelf-pin collision:** flag when a slide screw row and a
    pin row share a height band on the same side panel.
  - **Groove vs. back rabbet interference** on the carcass.
  - **CAD cross-check (opt-in):** when A2 geometry is on, assert no negative
    remaining-material regions (a cut deeper than the stock).
- **Tests (`tests/test_critic_joinery.py`, `tests/test_validator.py`):** each
  failure mode triggers, and a clean cabinet stays clean.
- **Acceptance:** a 15 mm door with a 35 mm cup is rejected with a clear repair
  note the designer loop can act on.
- **Effort:** M. **Risk:** low. **Depends on:** A2 only for the CAD cross-check;
  the analytic checks ship independently.

---

## Workstream B — Design kitchens, not boxes (appliances + counters)

**Goal:** a "design" can be a real kitchen run — sink base with the sink cut
out, a dishwasher void, a range gap, finished ends — and produce an appliance
schedule.

### B1 — A first-class appliance model in the DSL

Promote `appliance` from a loose accessory dict to a typed, validated concept.

- **Files:** `dsl.py` (new `Appliance` dataclass + enum), `accessories.py`,
  `validator.py`.
- **Tasks:**
  - `ApplianceType` StrEnum: `sink | cooktop | range | wall_oven | dishwasher |
    fridge | microwave | hood`.
  - `Appliance(type, width, height, depth, cutout_w, cutout_d, panel_ready)`,
    parsed from the existing `accessories` list for back-compat (keep accepting
    the dict form; normalize on load).
  - Validator rules per type: a `range`/`dishwasher` consumes a **gap, not a
    cabinet** (see B3); a `sink`/`cooktop` needs a host base of sufficient
    interior width and a counter to host the cutout; `panel_ready` requires an
    end/door panel to be present.
- **Tests (`tests/test_appliances.py`):** round-trip dict↔dataclass; a sink in a
  300 mm base errors; a panel-ready dishwasher with no panel warns.
- **Effort:** M. **Risk:** low. **Depends on:** nothing.

### B2 — Subtract appliance cutouts from the countertop (cut list + geometry + DXF)

Today the countertop is a full rectangle and the cutout is validation-only.

- **Files:** `accessories.py` (countertop part), `geometry.py` (counter solid),
  `dxf.py`, `cutlist.py`.
- **Tasks:**
  - Carry cutouts on the `Countertop` part as a list of `(x, y, w, d)` openings
    in the counter's own frame.
  - Cut list: note the cutout(s) and reduce finishable/material area for the
    quote; add a `Sink/cooktop cutout` line to the joinery/CNC ops.
  - Geometry (A2-style boolean): subtract the cutout from the counter solid.
  - DXF: draw the cutout as a closed polyline on a `CUTOUT` layer in the nest.
- **Tests:** counter area in the estimate drops by the cutout area; the DXF
  contains the cutout polyline; the STEP counter has the opening when A2 is on.
- **Effort:** M. **Risk:** low. **Depends on:** B1; A1/A2 for DXF/STEP cutouts.

### B3 — Appliance voids and gaps in a run

A dishwasher/range is a *space*, not a cabinet, and the run must reserve it.

- **Files:** `room.py`, `geometry.project_layout`, `validator` (project),
  `dsl` (Project component can be an `ApplianceVoid`).
- **Tasks:**
  - Add an `ApplianceVoid(width, type)` component kind that occupies run width
    and footprint but adds no carcass (it does add finished-end panels on
    exposed adjacent cabinet sides and a filler/scribe where needed).
  - `fit_run` accounts for void widths; the placement-overlap check treats a
    void as occupied space (no cabinet may overlap it).
  - Standard clearances: dishwasher ≈ 600 mm, range ≈ 760/900 mm — warn when a
    void is mis-sized for its appliance type.
- **Tests (`tests/test_room.py`, `tests/test_appliances.py`):** a 4-cabinet run
  with a DW void totals the wall correctly; a cabinet overlapping the void
  errors; exposed sides next to the void get end panels.
- **Effort:** M. **Risk:** med (touches the run/placement math). **Depends on:**
  B1.

### B4 — Appliance schedule in the build package

- **Files:** new `appliance_schedule()` (in `accessories.py` or a small
  `appliances.py`), `report.py`, `service.py`, web bundle.
- **Tasks:** list each appliance, its host cabinet/void, cutout size, required
  clearances, and panel-ready panels; add a section to the PDF and the web
  results; include rough-in notes (plumbing/electric) as free text.
- **Tests (`tests/test_report.py`):** the package renders an appliance section
  when appliances are present, and omits it otherwise.
- **Effort:** S. **Depends on:** B1.

---

## Workstream C — Snap to purchasable reality

**Goal:** the numbers the app emits match what a shop can actually buy and cut.

### C1 — Auto-snap drawer-box depth to a real slide length  ★ quick win

Slides ship in discrete lengths; box depth should target one.

- **Files:** `hardware.py` (catalog of standard lengths per family), `cutlist.py`
  (`_add_drawer_box`), `validator.py`.
- **Tasks:**
  - Add `STANDARD_SLIDE_LENGTHS` (e.g. 250/300/350/400/450/500/550/600 mm and
    18/20/22/24″) to the slide catalog.
  - When `Drawer.slide_length == 0`, pick the **longest standard slide that fits**
    `interior_depth − clearance`, size the box to it, and record the chosen
    length on the part note + hardware BOM.
  - Validator: warn when interior depth wastes a slide size (e.g. 560 mm cabinet
    forced to a 450 mm slide leaves > 80 mm unusable).
- **Tests (`tests/test_drawerbox.py`):** a 560 mm-deep base picks a 500 mm slide
  and box depth ≈ 500; the chosen length appears in the hardware BOM.
- **Effort:** S. **Risk:** low. **Depends on:** nothing.

### C2 — Per-edge edge-banding

Replace the single rough running-length line with which edges of which parts get
banded, and metres by banding material.

- **Files:** `cutlist.py` (per-`Part` `banded_edges`), `estimator.py` (banding
  cost from real metres), `report.py`.
- **Tasks:**
  - Add `banded_edges: str` to `Part` (e.g. `"L"` = one long edge, `"LLSS"` for
    all four) set where the build rules say an edge shows.
  - Estimator sums banding metres per material from the actual banded edges.
  - Package lists banding by material with total metres (orderable).
- **Tests (`tests/test_cutlist.py`, `tests/test_estimator.py`):** a frameless
  base bands the two side fronts + bottom front + stretcher front; metres match
  the summed edge lengths.
- **Effort:** M. **Risk:** low.

### C3 — Real stock thickness (nominal vs. actual) and grain-locked nesting check

- **Files:** `stock.py`, `materials.py`, `profile.py`, `packing.py`.
- **Tasks:**
  - Let a shop profile pin actual thicknesses (18 mm vs 19 mm/¾″) and have the
    joinery cut to the **actual** mating thickness (joinery.py already cuts "to
    mating thickness" — feed it the real number).
  - Confirm/extend `packing.pack` to honor grain (parts whose grain runs along
    length can't be rotated 90°); add a test that proves a grain-locked part is
    never rotated.
- **Tests (`tests/test_grain_nesting.py`, `tests/test_stock_labels.py`):** a
  grain-locked part stays un-rotated; joinery width tracks the profile's actual
  thickness.
- **Effort:** M. **Risk:** low.

---

## Workstream D — From design tool to shop product

**Goal:** the outputs a shop *acts on* — what to buy and from whom — and the
job/revision workflow around a real customer.

### D1 — Supplier-grouped purchase order

- **Files:** new `purchasing.py`, building on `estimator` + `hardware` catalog;
  `report.py`, `service.py`, web.
- **Tasks:**
  - Group the BOM into a PO by supplier/brand: sheet goods by species/grade/size,
    hardware by SKU/brand (from `hardware.py`), banding by roll, finish by litres
    (from `finishing.py`).
  - Emit CSV + a PDF PO page; totals reconcile with the quote.
- **Tests (`tests/test_purchasing.py`):** every quoted line appears on a PO line;
  hardware lines carry SKUs; sheet count matches the estimator.
- **Effort:** M. **Risk:** low. **Depends on:** C1/C2 for accurate quantities.

### D2 — Surface revisions in the web app

`diffing.py` already computes field-level spec diffs; expose it.

- **Files:** `web.py`, `service.py`, `static/index.html`, library/Convex layer.
- **Tasks:** version saved designs; show a revision list with `diff_summary`
  per change; a "what changed since last quote" panel (parts added/removed,
  price delta).
- **Tests (`tests/test_web.py`):** saving a changed spec yields a diff with the
  expected `{path, from, to}` rows and a price delta.
- **Effort:** M. **Risk:** low. **Depends on:** nothing (diffing exists).

### D3 — Customer-facing proposal / approval drawing

- **Files:** `report.py` (a second, customer-mode document), `drawings.py`,
  `service.py`, web "Proposal" download.
- **Tasks:** a clean proposal — render, elevations with overall dims, plain-
  language spec, price, and a sign-off block — distinct from the shop build
  package (no joinery/CNC detail).
- **Tests (`tests/test_report.py`):** the proposal renders without the bench
  sections; the build package keeps them.
- **Effort:** S. **Depends on:** existing drawings/report.

---

## Sequencing & milestones

**Milestone 1 — "Honest outputs" (highest leverage, lowest risk).**
A1 (bores in DXF) · C1 (slide snapping) · A3 analytic checks · B1 (appliance
model). All small/medium, no OCC risk, immediately more shop-usable.

**Milestone 2 — "Real kitchens."**
B2 (counter cutouts) · B3 (voids/gaps) · B4 (appliance schedule) · C2 (per-edge
banding). The unit of design becomes a room.

**Milestone 3 — "Machine-ready geometry."**
A2 (joinery in STEP, behind a flag) · A3 CAD cross-check · B2/B-cutouts in STEP.
Highest effort; gated so it never blocks shipping.

**Milestone 4 — "Shop product."**
D1 (purchase order) · D2 (revisions) · D3 (proposal) · C3 (stock realism).

## Guardrails (keep what makes this good)

- **Single source of truth:** every new output reads from `geometry.panel_layout`
  / `joinery_schedule` / `drilling_schedule` — never a second copy of the math.
- **Degrade gracefully:** new geometry (A2/B2 booleans) is opt-in and falls back
  to today's behavior on any failure; CAD-free paths stay CAD-free.
- **Test parity:** every item lists tests; the suite (currently 507 passing)
  must stay green, and slab-mode geometry must be regression-identical.
- **No silent truncation:** when nesting/clearances drop something, surface it.

## Rough effort

| Milestone | Items | Size |
|---|---|---|
| 1 | A1, C1, A3(analytic), B1 | ~1–1.5 wk |
| 2 | B2, B3, B4, C2 | ~2 wk |
| 3 | A2, A3(CAD), cutouts-in-STEP | ~2–3 wk (OCC risk) |
| 4 | D1, D2, D3, C3 | ~2 wk |
