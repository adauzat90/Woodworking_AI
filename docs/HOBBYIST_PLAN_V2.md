# Hobbyist Plan V2 — from "very good" to "truly great"

This is the sequel to [`HOBBYIST_ROADMAP.md`](HOBBYIST_ROADMAP.md) (the H-series,
now largely shipped: species DB, leaf-furniture refactor, shelves/boxes/benches,
cut-from-stock, skill+time planning, finishing/glue-up depth). It turns the
**second** hobbyist review into concrete, code-grounded engineering work, in
impact order. It uses a **G-series** id (G = "great") to avoid colliding with the
H-series.

Every phase keeps the invariants this codebase already holds, and these are
**non-negotiable**:

- the business core stays **pure-math, no CAD dependency** (runs and unit-tests
  anywhere; `build123d`/`reportlab`/`matplotlib`/an API key are always optional);
- geometry has a **single source of truth** — `geometry.panel_layout` feeds both
  the builder and the Critic; never add a second placement path;
- new furniture routes through the **leaf-furniture registry** (`furniture.register`)
  and **`dispatch.spec_kind`**, not fresh `isinstance` ladders or stage edits;
- every feature **degrades gracefully** when an optional dep is absent;
- **golden tests** (`tests/test_golden.py`, `tests/golden_specs.py`) pin current
  output byte-for-byte — a refactor is correct iff the goldens stay green.

---

## Already shipped — verified in the codebase, do **not** rebuild

The first review under-counted what exists. Confirmed present and working:

| Reviewed as "missing" | Reality |
|---|---|
| Collada `.dae` export for SketchUp | `exporters.export_dae` (via trimesh) ✓ |
| Per-part STEP/STL export | `exporters.export_parts_step` / `export_parts_stl` ✓ |
| Aggregated shopping list | `purchasing.py` → `purchase_order` bundle: supplier-split lines for **sheet, lumber, hardware, banding, finish, labour**, with SKU/brand and CSV ✓ |
| Imperial plywood reality (¾″ = 23/32″) | `stock.py` nominal→actual map (18.3 mm) ✓ |
| Wood-species data behind the label | `species.py` (14 woods: Janka, E, movement, finish, $/bd-ft) ✓ |
| Example loader in the web UI | `#projectSample` / `#load example` selector ✓ (project-JSON only — see G3) |
| Explode factor for the 3D model | `model_sections` + explode wired in `service.py`/UI (static, not a *walkthrough* — see G2) |

So this plan **extends** those rather than duplicating them. The genuinely-open
items follow.

---

## G1 — Furniture coverage for the home shop (★★★ highest)

**Why.** Today: cabinets (7), table, wall shelf, box/chest, bench/stool. The
projects a hobbyist actually starts with — a **bed**, a **picture/mirror frame**,
a **nightstand**, a **workbench**, a **cutting board**, a **desk** — aren't yet
modellable. This is the single highest-value addition and the post-H0 path makes
each one cheap.

**The leaf recipe (followed for every type below — no generic-stage edits).**
1. Spec dataclass in `dsl.py` with `kind`, `from_dict`/`to_dict`, and
   imperial-on-load (`_to_mm`) — copy `WallShelfSpec`/`BoxSpec` as the template.
2. A kind constant + `spec_kind` branch in `dispatch.py`.
3. A `spec_from_dict` route + a `DSL_SCHEMA_HINT` block in `dsl.py` (so the AI
   designer can author it).
4. Register the five stages where each is owned:
   `geometry.register(KIND, panels=…)`, `cutlist.register(KIND, cut_parts=…)`,
   `validator.register(KIND, validate=…)`, `joinery.register(KIND, joinery_ops=…)`,
   and an optional `assembly_steps.register(KIND, assembly=…)` (else the default
   plan applies).
5. Type-specific hardware in `hardware.py`.
6. `tests/test_<type>.py` — runs with **no** CAD/API key (pure math).

Ship in impact order; each reuses existing primitives so it stays small.

1. **Picture / mirror frame** *(S)* — 4 mitered or cope-and-stick rails + a
   **rabbet** for glass/backer. Reuses rail-and-stile joinery (`joinery`) and the
   rabbet logic. Hardware: turn-buttons / sawtooth hanger / D-rings in
   `hardware.py`. Proves the recipe fastest.
2. **Nightstand / legged cabinet with a drawer** *(M)* — a `LeggedSpec`-style
   base (top + 4 legs + aprons, already in `TableSpec`/`BenchSpec`) carrying a
   small **drawer box** (reuse `cutlist` drawer-box parts + slide hardware). Most-
   requested "next project" after a table.
3. **Bed** *(M–L)* — headboard + footboard (**frame-and-panel**, already built by
   `cutlist._add_door_parts`) + side rails joined by **knock-down bed-bolt /
   hook** hardware + a **slat deck**. New hardware entries only; geometry reused.
4. **Workbench** *(M)* — a heavy `BenchSpec` superset: thick top (laminated
   glue-up — `species`/estimator already price board-foot glue-ups), a stretcher
   base, optional **vise** mounting voids and **dog holes** (a 19 mm row — reuses
   the `drilling` schedule generator). High hobbyist value; shows off the tooling
   + planning stack.
5. **Cutting / charcuterie board** *(S)* — an **edge- or end-grain glue-up**
   panel: a `GlueUpSpec` over N strips with alternating species/grain. Reuses the
   glue-up board breakdown + board-foot pricing; output is a **glue-up layout**
   (strip order, widths, cull list). Tiny geometry, beloved beginner project.
6. **Desk** *(M)* — a `table`/legged superset with an apron-hung drawer and an
   optional modesty panel + grommet void. Mostly composition of (2).

**Explicit non-goals (keep the DSL honest):** **chairs** (compound seat/back
angles, ergonomic curves, steam-bending — a different engine), and anything
requiring bent lamination or carving. Document in the schema hint.

**Files per type:** `dsl.py`, `dispatch.py`, `hardware.py`, `tests/test_<type>.py`,
plus the five `register(...)` calls in their home modules. **No** edits to the
generic stages. **Size:** S–M each. **Risk:** low (leaf path is proven by shelf/
box/bench). **Depends on:** nothing new.

---

## G2 — Interactive design & an exploded assembly **walkthrough** (★★★)

**Why.** The app is form/AI-driven and the model is a static GLB; the assembly
sequence (`assembly_steps.py`) is text-only. The single biggest "feels like a
real shop tool" upgrade is letting the model **show the build**, step by step.

**Plan (two independent pieces; ship G2a first).**

- **G2a — Exploded, stepwise assembly walkthrough.** The data already exists:
  `panels_by_subassembly(spec)` (the `model_sections`) and the assembly `plan`
  with `part_ids` per step. Wire them together in the web UI:
  - extend the GLB/section bundle in `service.py` so each `model_section` carries
    its **part IDs** and its **sub-assembly + step order** (no new geometry — just
    join existing maps);
  - in `static/index.html`, add a **"Build steps" player**: a step slider that
    (1) highlights/isolates the parts for the current step in `<model-viewer>`
    and (2) scrolls the matching `assembly_steps` text + cut-list rows into view.
    Reuse the existing **explode factor** so "show all steps" fans the model out.
  - Pure front-end + one bundle field; degrades to the current static view when
    GLB is unavailable.
- **G2b — Direct dimension editing on the model.** Overlay the three primary
  dimensions (W/H/D, from `drawings.label_dims`) on the `<model-viewer>` as
  draggable handles that write back to the parameter form and trigger the
  existing **live-update** rebuild. No engine change — it drives the same
  `POST /api/build` path. Start read-only (dimension annotations), then make the
  handles editable.

**Files:** `service.py` (section↔step↔part-id join), `static/index.html`
(player + overlay), `tests/test_web.py` (the bundle exposes step→part-id
mapping). **Size:** M (G2a) + M (G2b). **Risk:** low–medium, all additive and
front-end-gated. **Depends on:** nothing (uses shipped data).

---

## G3 — Onboarding: a starter-project gallery (★★)

**Why.** A cold visitor sees a parameter form and a JSON box. The only "examples"
today are three **project-JSON** samples (`#projectSample`) — not approachable
furniture starters. A hobbyist needs "click **Bookshelf / Nightstand / Blanket
chest / Workbench**, get a working design to modify."

**Plan.**
- A small curated set of named starter specs (reuse the real ones in
  `tests/golden/*.json` and `examples/*.py` so they're guaranteed-valid).
- Serve them from a new `GET /api/templates` (id, label, thumbnail, spec) backed
  by a `templates.py` registry; thumbnails are the existing headless
  `render_png` (pre-rendered at build time, or on first request, cached).
- A **gallery strip** at the top of `static/index.html`: click a card → load the
  spec into the form/JSON and build. Works with zero API key (parametric path).

**Files:** new `templates.py`, `service.py`/`web.py` (`/api/templates`),
`static/index.html` (gallery), `tests/test_web.py`. **Size:** S–M. **Risk:** low.
**Depends on:** ideally lands **after** G1 so the gallery can feature the new
types.

---

## G4 — Shopping & sourcing depth (★★)

**Why.** `purchase_order` already aggregates sheet/lumber/hardware/banding/
finish/labour with supplier split and SKUs. Two gaps remain for a hobbyist:
**consumables aren't ordered**, and there's **no "where to buy."**

**Plan.**
- **G4a — Consumables lines** in `purchasing.py` (a `_consumable_lines` builder):
  - **glue** by the bottle, sized from the glue-up/joint count
    (`planning._glue_up_count` + joint area);
  - **abrasives** (sandpaper) from the `finishing` grit sequence × sanded area;
  - **clamps** from the existing `assembly_steps` clamp schedule (count + length)
    — flagged as *own/buy* against the `tooling` checklist, not a forced purchase;
  - **fasteners/finish-supplies** (screws already in the BOM; add brushes/rags/
    conditioner when `species` finishing notes call for it).
  Each carries a `category` so the CSV/print view groups it. Gated so a zero
  quantity emits no line.
- **G4b — Sourcing map.** A `sources.py` table mapping each hardware brand/part
  and each consumable to a **retailer + optional buy-URL** (Rockler / Lee Valley /
  big-box), plus a **big-box equivalent** for the Euro brands (Blum/Hettich/Grass
  → generic home-center hinge/slide). Surface as an optional `source`/`url` field
  on each `POLine`; render as links in the web **purchase order** tab. Advisory —
  never blocks the math, and prices stay overridable via the `ShopProfile`.
- **G4c — Printable shopping list.** A print-friendly view/section of the PO
  (grouped by store) — falls out of G5's print stylesheet + the existing CSV.

**Files:** `purchasing.py` (consumables + `source` field), new `sources.py`,
`service.py` (expose `source`/`url`), `static/index.html` (links + print),
`tests/test_purchasing.py`. **Size:** M. **Risk:** low (additive, data-driven).
**Depends on:** G5 for the print view (G4c only).

---

## G5 — Mobile / at-the-bench usability (★★)

**Why.** The UI has a single fixed `grid-template-columns:340px 1fr` and **one**
`@media` rule. Plans get *used* at the bench on a phone/tablet. Two concrete
deliverables:

**Plan.**
- **Responsive layout** — collapse the 340 px sidebar to a top drawer / tabbed
  panel under a breakpoint; let the 3D view and result tabs go full-width; ensure
  touch targets and the tab bar work one-handed. Pure CSS + a little JS for the
  drawer toggle in `static/index.html`.
- **Print stylesheet** — a `@media print` that prints the **cut list, drilling
  schedule, shopping list, and assembly steps** as clean, paginated black-on-white
  (hide the 3D canvas/controls; expand collapsed tabs). This is the artifact a
  hobbyist tapes to the wall — today there's only the reportlab PDF and CSV.

**Files:** `static/index.html` (CSS + drawer JS only). **Size:** S–M. **Risk:**
low; no backend change. **Depends on:** none (but pairs with G4c).

---

## G6 — Polish (★)

- **G6a — 1:1 full-size templates** *(S)*. For tapers, the diagonal-corner face,
  splayed legs, and frame profiles, tile the existing `drawings.py` SVG across
  multiple pages into a **printable PDF** (reportlab page-tiling in
  `pdf_common.py`/`report.py`), with registration marks + a 100 mm/4″ **scale
  check** square. Print, spray-glue, cut to the line. New download button +
  `tests/test_drawings.py` / `tests/test_report.py` case. Degrades when reportlab
  is absent.
- **G6b — Imperial-first default** *(S)*. `ShopProfile.units` already exists but
  defaults to mm and isn't honored as the *default* across surfaces. Make the
  CLI/web default to fractional inches **when the profile sets it** (engine stays
  mm-native — display only, the `units.py` layer already exists). Update
  `tests/test_units.py` / `tests/test_web.py`.
- **G6c — Verify PO consumables flow into the build-package PDF** *(XS)* — once
  G4a lands, confirm `report.py`'s PDF picks up the new lines (it reads the same
  bundle).

**Size:** S each. **Risk:** low.

---

## G7 — Housekeeping: the two failing exports (must-fix)

**Why.** On a fresh `pip install -e ".[all]" && pytest`, two tests fail:
`tests/test_export_cad.py::test_export_parts_step_stl` and
`tests/test_critic_joinery.py::test_negative_material_check_skips_without_build123d`,
both tracing to OpenCascade **`Failed to write STEP file`**. STEP/per-part export
is a headline feature, so a silent break here is bad.

**Plan.**
- Reproduce and pin the root cause — likely an OCP/`build123d` **STEP writer**
  behaviour in some environments (e.g. an empty/degenerate compound, a write-
  permission/temp-path issue, or a version skew between `build123d` and the OCP
  wheel). Determine whether it's environmental or a real regression in
  `exporters._export_parts`.
- Make the writer robust: validate the model is non-empty before writing, surface
  the OCP status, and **skip-with-reason** rather than hard-fail when the platform
  can't write STEP (mirroring the graceful-degradation rule the second test
  already encodes for the no-build123d path).
- Add a regression test that asserts a clear, typed error/skip instead of a raw
  `RuntimeError`.

**Files:** `exporters.py`, `tests/test_export_cad.py`,
`tests/test_critic_joinery.py`. **Size:** S. **Risk:** low. **Priority:** do this
**first** — green suite is the baseline every other phase builds on.

---

## Suggested sequence

```
G7 (fix exports)  ──▶ green baseline
  │
G1 (furniture: frame → nightstand → bed → workbench → board → desk)
  │                                   │
  ├──▶ G3 (starter gallery features the new types)
  │
G2a (assembly walkthrough) ──▶ G2b (drag dimensions)
  │
G4 (consumables + sourcing) ──┐
G5 (responsive + print)      ─┴──▶ G4c (printable shopping list)
  │
G6 (templates, imperial-first, PDF check) — filler between the big phases
```

1. **G7 first** — restore a fully green suite (the contract every refactor below
   relies on).
2. **G1** — the headline value; ship one type at a time (each behind the proven
   leaf path, generic stages untouched).
3. **G2a → G3** — make the result *legible and approachable* (the walkthrough and
   the gallery turn a powerful engine into a friendly app).
4. **G4 + G5** — close the "now go buy and build it" loop (sourcing + a print-
   ready shopping list and plan).
5. **G2b + G6** — direct-manipulation polish and the small wins, slotted as
   filler.

## Summary table

| # | Item | Impact | Size | Depends on |
|---|---|---|---|---|
| **G7** | Fix STEP / per-part export tests | gate | S | — |
| **G1** | Furniture: frame, nightstand, bed, workbench, board, desk | ★★★ | S–M each | leaf path ✓ |
| **G2a** | Exploded stepwise assembly walkthrough | ★★★ | M | sections/plan ✓ |
| **G2b** | Drag-to-edit dimensions on the model | ★★ | M | live-update ✓ |
| **G3** | Starter-project gallery | ★★ | S–M | G1 (ideally) |
| **G4** | Consumables + sourcing/buy-links in the PO | ★★ | M | PO ✓ |
| **G5** | Responsive layout + print stylesheet | ★★ | S–M | — |
| **G6** | 1:1 templates, imperial-first default, PDF check | ★ | S each | reportlab opt. |

Each phase keeps the suite green, adds **no** CAD dependency to the core, and
ships its own tests that run without an API key or `build123d`.
