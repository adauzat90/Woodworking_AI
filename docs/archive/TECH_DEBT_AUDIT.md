# Tech Debt Audit — Woodworking AI

> Date: 2026-06-25 · Scope: `src/woodworking_ai/**` (~10.3k LOC, 39 modules) +
> `static/index.html`. Method: full read of every module, cross-checked against
> the architecture doc's stated invariants. Findings are graded
> **HIGH / MED / LOW** by risk × effort-to-fix, with `file:line` references.

This codebase is in good shape overall: it has a clear architecture doc, a real
test suite (50+ test files), a clean units layer, and an explicit
`test_techdebt.py` that locks in earlier de-duplications. The findings below are
the *next* layer of debt — much of it is the gap between what the architecture
doc *claims* is unified and what the code actually does.

---

## 0. The five headline issues

| # | Issue | Severity | Where |
|---|---|---|---|
| 1 | **Spec-type dispatch is re-implemented in 12+ modules** — the central extensibility ceiling | HIGH | every pipeline stage |
| 2 | **"Single source of truth" is violated 3 ways** — drawer-box dims, 5-piece door dims, and category styling are each computed twice | HIGH | geometry vs cutlist; render vs drawings |
| 3 | **Construction constants are duplicated — and one set conflicts** — slide clearance is `13.0` in one module and `12.7` in three others | HIGH | constants vs hardware/validator/dsl |
| 4 | **CLI re-implements the bundle pipeline that `service.py` owns** | HIGH | cli.py vs service.py |
| 5 | **Reflected XSS + swallowed exceptions** — error text flows to `innerHTML`; B-Rep failures are reported as "no collision" | HIGH | index.html; critic.py; web.py |

---

## 1. Extensibility — the spec-type dispatch problem (HIGH)

The architecture doc states (§6) that the pipeline "dispatch[es] on the spec
type, so new furniture plugs into the whole pipeline." In practice **each stage
re-implements the same `isinstance` ladder**, so adding one furniture type means
editing ~12 functions in lockstep — classic *shotgun surgery* from missing
polymorphism.

The identical `ApplianceVoid → ComponentGroup → TableSpec → (cabinet default)`
ladder appears in:

```
geometry.py:327      cutlist.py:593      validator.py:349    estimator.py:319
drilling.py:149      joinery.py:212      assembly_steps.py:312  appliances.py:103
builder.py:282       purchasing.py:245   render.py:130       agents/critic.py:378
```

**Remediation.** Define a `Spec` protocol (or ABC) with the operations each
stage needs — `layout()`, `cutlist()`, `validate()`, `estimate()`, etc. — and
let each spec class implement them (or register handlers in a dispatch table
keyed by type). Each pipeline function then calls `spec.layout()` instead of
branching. A new furniture type becomes *one new class*, not 12 edits. This is
the single highest-leverage refactor in the codebase.

---

## 2. "Single source of truth" violations (HIGH)

The doc's strongest claim (§4) is that panel placement "lives in one place …
consumed by *both* the compiler and the Critic … they cannot drift apart." That
holds for *placement*, but three sets of **dimensions** are computed twice:

- **Drawer-box dimensions** — `geometry.py:590-621` (`_drawer_box_panels`) and
  `cutlist.py:397-434` (`_add_drawer_box`) each independently derive box width /
  height / depth from `SLIDE_SIDE_CLEARANCE`, `DRAWER_BOX_HEIGHT_DROP`,
  `DRAWER_BOX_DEPTH_GAP` — *with different clamps* (geometry floors width at
  `80.0`; cutlist does not). The 3D model and the cut list can disagree.
- **5-piece door member dimensions** — `geometry.py:547-587` (`_door_panels`)
  vs `cutlist.py:437-472` (`_add_door_parts`) each derive stile/rail/panel sizes
  from `DOOR_STILE_WIDTH` / `DOOR_RAIL_WIDTH`.
- **Category → display style** — `render.py:19-32` (`CATEGORY_COLORS`, 10
  categories) vs `drawings.py:180-188` (`_STYLE`, CSS, ~2 categories). They
  disagree, and `drawer_box` is missing from `CATEGORY_COLORS` entirely (falls
  to the `#bbbbbb` default at render.py:49).

**Remediation.** Extract `drawer_box_dims(spec, opening_w, front_height)` and
`door_part_dims(item/spec)` helpers consumed by both geometry and cutlist; add a
test asserting panel dims == part dims (the existing
`test_front_panels_and_parts_share_dimensions` covers fronts — extend it to
drawer boxes). Share one category→style table between render and drawings.

---

## 3. Duplicated & conflicting construction constants (HIGH)

`constants.py`'s docstring states the intent: "Centralised here … easy to tune
in one place." The code has drifted from it. Core shop constants are redeclared
across modules, and one pair **conflicts**:

| Constant | Definitions | Conflict? |
|---|---|---|
| 32 mm system pitch | `drilling.py:26 SYSTEM_PITCH`, `validator.py:49 SYSTEM_PITCH`, `hardware.py:29 PLATE_SCREW_PITCH`, raw `32.0` at `drilling.py:206` | no — same value, 3 names |
| Hinge cup (`35.0 / 12.5 / 22.5`) | `hardware.py:26-28`, `validator.py:37-39`, `drilling.py:31-33` | no — 3 copies |
| Side-mount slide clearance | `constants.py:17 = 13.0` **but** `hardware.py:76`, `validator.py:29`, `dsl.py:207` all `= 12.7` | **YES** |

The slide-clearance conflict is a real bug surface: the cutlist/geometry path
(via `SLIDE_SIDE_CLEARANCE = 13.0`) computes a drawer-box width 0.6 mm narrower
than the hardware/validator path (`12.7`).

**Remediation.** Move `SYSTEM_PITCH`, the hinge-cup trio, and *one* slide
clearance into `constants.py`; import everywhere; delete the copies. Reconcile
12.7 vs 13.0 deliberately (½″ = 12.7 mm, so 12.7 is likely correct). Also fold
`HOUSED_DEPTH_FRACTION`/`GROOVE_BACK_INSET` (joinery.py), `COVERAGE_M2_PER_L`
(finishing.py), and the accessory defaults (accessories.py) back into
`constants.py`. Note `constants.py:13 BACK_RABBET = 0.0` is a dead no-op.

---

## 4. Coupling & duplicated pipelines (HIGH/MED)

- **CLI bypasses the service layer (HIGH).** `cli.py:27-214` (`_emit` /
  `_emit_project`) re-runs the full assembly — validate, critique, cutlist,
  estimate, drilling, joinery, assembly, exporters — that `service.build_result`
  / `service.export_bytes` already centralize for the web app. `service.py`'s
  docstring claims to be the "one place" for this. Two pipelines *will* drift
  (different defaults, missing sections). And `_emit` vs `_emit_project` are
  themselves ~90% identical. **Fix:** the CLI should call
  `service.build_result()` / `export_bytes()` and only handle text/CSV
  presentation and file writing.

- **Agents import private internals (HIGH).** `critic.py` imports
  underscore-private functions from sibling modules:
  `validator._joinery_feasibility` (270-278), `builder._require_build123d`
  (345, 503). This couples the Critic to internals that can change silently.
  **Fix:** promote to public APIs (`validator.joinery_feasibility`,
  `builder.require_build123d`).

- **`purchasing.py:30` imports `estimator._sheet_price`** (MED) — same private-
  symbol coupling. Promote to a public pricing function.

- **Web/CLI both shape bundles; the SPA duplicates the pricing-merge contract**
  (MED) — `web.py:_pricing_overrides` logic also lives in `index.html`. Define
  request models and a single pricing contract.

---

## 5. Security & error-handling (HIGH/MED)

- **Reflected XSS (HIGH).** `static/index.html:595-596` sets
  `$("status").innerHTML = '…' + msg + '…'` where `msg` is the API error
  `detail`, which itself contains `str(exc)` built from user-influenced spec
  data. 13 `innerHTML` sites total (e.g. 788, 1168, 1237). **Fix:** use
  `textContent` for all dynamic/error text, or escape before insertion.

- **Swallowed B-Rep failures defeat the Critic (HIGH).** `critic.py:156-159`
  does `except Exception: vol = 0.0` — *any* boolean-kernel failure is reported
  as "no interference," i.e. a clean model. **Fix:** catch the specific
  disjoint-solids case; on unexpected errors emit a `warning` issue.

- **Unbounded paid LLM cost (MED).** `web.py:146` passes
  `payload.get("attempts", 3)` straight into the repair loop — a client can
  request a huge value, each an LLM round-trip (DoS / cost). `factor`
  (web.py:169) similarly unbounded. **Fix:** clamp via a Pydantic request model.

- **Info leak + broad catches (MED).** `web.py:129/176/237` return
  `detail=f"…: {exc}"`, leaking internal state; `service.py:69-82` and
  `builder.py:189/218` swallow every exception into `None`/`{}`. **Fix:** log
  server-side, return generic messages, narrow exception types.

- **Untyped request bodies (MED).** Handlers take `dict[str, Any]` and manually
  `payload.get(...)`, discarding FastAPI's validation/OpenAPI value
  (`web.py:122/134/157/182/209/224`). Define Pydantic request models.

---

## 6. God-functions / long methods (MED)

| Function | Lines | Concern |
|---|---|---|
| `cutlist.generate_cutlist` | ~200 (591-798) | carcass+back+shelves+toe+frame+fronts+drawers+hardware+accessories inline |
| `geometry.panel_layout` | ~120 (325-443) | type dispatch + carcass + face-frame + fronts |
| `service.build_result` | ~175 (167-343) | assembles ~15 sub-bundles inline w/ local imports |
| `assembly_steps._cabinet_plan` | ~170 (104-273) | part-classification + sub-assembly + step gen |
| `drilling.drilling_schedule` | ~105 (148-253) | pins + slides + hinges + plates inline |
| `designer.design_from_prompt` | ~70 (49-116) | prompt + parse + validate + critique + feedback |

**Fix:** split each into the per-section helpers already hinted at by the
`_add_*` / `_*_panels` naming conventions, with the top-level function as a thin
orchestrator. This also de-risks the §1 polymorphism refactor.

---

## 7. Duplicated report/PDF code (HIGH within that subsystem)

`report.py` and `proposal.py` share large copy-pasted reportlab blocks:

- `_elevation_flowable` (proposal.py:35-95) ≈ `_drawings_flowable`
  (report.py:36-97) — ~60 near-identical lines (same scale math, view loop,
  dimension callouts), differing only in colors / whether part IDs print.
- `_model_image` duplicated (proposal.py:98-109 vs report.py:148-167).
- `tbl()` + `TableStyle` defined twice inside report.py (272-285, 349-362) and
  the `mini`/`small` paragraph styles repeat across both files.

**Fix:** a shared `pdf_common.py` with the elevation Flowable (parameterized by
`show_ids`/colors), the model-image helper, and the table/paragraph styles.

---

## 8. Pervasive smell: stringly-typed dispatch (MED)

Throughout the code, behavior is driven by substring/prefix matching on
free-text labels instead of structured fields — brittle to any rename:

- `label.startswith("Door")` to decide where hinge bores draw
  (drawings.py:54-69, 87, 108).
- `"rear"/"back"/"top" in reference` to place joinery cuts (builder.py:106-123);
  unknown references silently fall to a "bottom" default.
- `p.label.startswith("Side")` / `"Drawer front"` in drilling.py:162-169.
- `_part_category` reverse-engineers a part's role from `"box" in name and
  "drawer" in name` (cutlist.py:136-153).
- `"slide"/"hinge"/"pull" in h.lower()` to link assembly steps to hardware
  (assembly_steps.py:154, 250-263).
- The `"".join(c for c in n if c.isdigit())` index-parse idiom recurs 4×
  (geometry.py:459/498/502, cutlist.py:218, drilling label parsing).
- `drilling.py:35/212` uses **exact float equality** `if d == 0.5` as a control
  sentinel — a genuine correctness smell.

**Fix:** carry explicit `category` / role / edge enums on `Part`, `PanelBox`,
and joinery ops at creation time; add one `_trailing_index(name)` regex helper.

---

## 9. Data that should be data-driven (MED)

- **Joint dispatch** — `joinery.py` has three parallel if/elif chains
  (`_housed_joint` 7-way, `_table_joinery` 4-way, drawer corners 4-way) mapping
  joint name → `(tool, width, depth, note)` tuples. Replace with one lookup
  table. (Also `joinery.py:219-223` has a dead `CORNER_DIAGONAL` branch
  identical to its fall-through.)
- **Appliance metadata split in two** — `appliances.py:25-53` (`_ROUGH_IN`,
  `_CLEARANCES`) vs `accessories.py:140-173` (per-type counter/gap rules) encode
  the same appliance vocabulary in two places. Consolidate near
  `APPLIANCE_VOID_WIDTHS` in dsl.py.
- **`hardware._PULLS` (142-147)** is four identical rows (all "Bar pull 96mm")
  differing only by a placeholder SKU — collapse to one until real parts exist.
- **`profile.py`** enumerates its field list 4× (31-38, 70-82, 89-103, 134) —
  drive (de)serialization from `dataclasses.fields()`.

---

## 10. Parallel taxonomies (MED)

Several hand-maintained tables encode overlapping "what role / how does this
read on a shopping list" vocabularies that must be kept in sync manually:

- cutlist.py: `SOLID_LUMBER_MATERIALS`, `_CATEGORY_PREFIX`, `_CATEGORY_TO_AREA`,
  `_PANEL_LABEL_TO_PART`
- materials.py: `AREA_ALIASES`, `FORM_LABELS`
- stock.py: `STOCK_DESCRIPTIONS`
- finishing.py: `_HIDDEN` / `_BOTH_FACES` material-tag literals

**Fix:** define the material/role taxonomy once (materials.py is the natural
home) and derive the rest; centralize the material-tag string vocabulary so a
rename can't silently break finishing/assembly/report.

---

## 11. Smaller items (LOW)

- **Dead code:** `geometry.py:445-448` — an unreachable duplicate
  `_accessory_panels(...)` + `return` after the real `return` at 443 (verified).
  `render.py:_isometric` takes an unused `spec` param.
  `diffing.py:_part_rows`/`quote_diff` take unused `prices`/`sheet`.
- **Imports inside function bodies** for no optional-dep reason:
  `import math` in render.py:79 and drilling.py:119; `import base64` in
  llm.py:50; various local re-imports in cli.py / service.py / critic.py.
- **Hardcoded literals re-deriving units:** `25.4` / `304.8` in engineering.py
  and stock.py instead of importing `MM_PER_IN` / `MM_PER_FT` from units.py.
- **DXF emission** (dxf.py:33-53) hand-builds raw R12 group-code pairs as flat
  string lists — one transposed magic code corrupts the file. Wrap in a typed
  entity builder. The part-frame→sheet rotation transform is copied 3×
  (drilling bores, dxf cutouts, dxf joinery) — extract one mapping helper.
- **`estimator.py:281`** merges component utilizations by `max(...)`, an
  optimistic, physically meaningless combined utilization. `Estimate._rate` is
  set by external private-attr poke (154/309/325/411) rather than a ctor arg.
- **`exporters.py`** — `export_step/stl/glb` are 3 near-identical wrappers; one
  `_export(model, path, fn)` would do.
- **No single LLM abstraction** — `llm.py:34` hardcodes `anthropic.Anthropic()`
  at every call site; a `LLMClient` protocol would allow a test fake / second
  provider. `DEFAULT_MODEL` is captured at import (llm.py:16), so post-import
  env changes don't take effect.
- **`web.py` recomputes capabilities and re-injects `CONVEX_URL` via string
  replace on every request** (41-62) — compute once at startup; cache the SPA
  HTML.

---

## Suggested sequencing

1. **Correctness first (small, high-value):** reconcile the 12.7/13.0 slide
   clearance; fix the `innerHTML` XSS; stop swallowing B-Rep exceptions in the
   Critic; clamp `attempts`; delete the geometry.py:445-448 dead code.
2. **Unify constants** into `constants.py` and import everywhere.
3. **Extract the duplicated dimension helpers** (drawer box, door members) and
   add drift-guard tests.
4. **Route the CLI through `service.py`**; promote the private symbols
   (`_joinery_feasibility`, `_require_build123d`, `_sheet_price`) to public.
5. **De-duplicate the PDF subsystem** into `pdf_common.py`.
6. **The big one:** introduce the `Spec` protocol and collapse the 12-module
   `isinstance` ladder into polymorphic dispatch — do this last, on top of the
   now-extracted helpers, so each `spec.method()` body is already small.
