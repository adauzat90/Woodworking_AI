# Hobbyist Roadmap — making it great for the home shop

This plan turns the remaining items from the woodworker's review into concrete
engineering work, written against the current codebase. It is the sequel to
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (the "shop product" workstream,
✅ complete) and picks up where the **shop-tooling inventory** left off.

> **Most of the H-series below is now shipped.** The next round of hobbyist work
> — beds/frames/nightstands/workbenches, an exploded assembly walkthrough, a
> starter-project gallery, sourcing/buy-links, and mobile/print — is planned in
> [`HOBBYIST_PLAN_V2.md`](HOBBYIST_PLAN_V2.md).

## Already shipped (do not re-build)

- **Design against your tooling** — `tooling.ShopTooling` (capability flags +
  presets), joint→tool feasibility, feasible-substitute suggestions, the
  validator advisory (`validator.validate(spec, tooling=…)`), the AI-designer
  constraint (`agents/designer.designer_constraint`), profile persistence
  (`profile.ShopProfile.tooling`), the service `tools` checklist, the web
  **My shop tooling** panel + **Tools** tab, and the CLI `--shop/--tools`.
  This delivered the review's *hand-tool mode (tooling side)* and the
  *tool-list output*. Tests: `tests/test_tooling.py`, `tests/test_web.py`.

## What this plan covers

| # | Gap from the review | Impact | Size | Depends on |
|---|---|---|---|---|
| **H1** | Furniture types beyond cabinets & tables (beds, benches, chests, shelves, frames) | ★★★ highest | L | H0 refactor |
| **H2** | "Build from the lumber I already have" — cut plan from owned boards | ★★★ | M–L | — |
| **H3** | Build plan: **skill level** + **realistic, method-aware time** | ★★ | M | tooling ✓, H5 |
| **H4** | Finishing depth + **glue-up / dry-fit / clamping** checklist | ★★ | S–M | H5 |
| **H5** | **Wood-species database** (properties behind the species label) | ★★ foundational | S–M | — |
| **H6** | Smaller wins: SketchUp/Collada export, per-part STEP, 1:1 templates, imperial-first | ★ | S each | — |

**Design rules every phase keeps** (the invariants this codebase already holds):
the business core stays **pure-math, no CAD dependency** (so it runs and unit-
tests anywhere); geometry has a **single source of truth** (`geometry.panel_layout`
feeds both the builder and the Critic — never add a second placement path); new
types route through **`dispatch.spec_kind`**, not fresh `isinstance` ladders; and
every feature **degrades gracefully** when `build123d` / `reportlab` / an API key
is absent.

---

## H0 — Refactor first: a leaf-furniture protocol (enables H1 cheaply)

**Why.** `dispatch.spec_kind` unified the VOID/GROUP/TABLE/CABINET routing, but
each leaf *still* hand-codes its logic inside the stages: cabinets and tables
each have their own branch in `geometry.panel_layout`, `cutlist.generate_cutlist`,
`validator`, `joinery`, `assembly_steps`, and `render`. Adding a fifth type today
means editing all of them in lockstep — the "shotgun surgery" the tech-debt audit
flagged. Fix that **once** so every new type in H1 is cheap.

**Plan.** Introduce a small registry/protocol for *leaf furniture*:

- `furniture.py` (new): a `LeafFurniture` Protocol with the methods a leaf must
  provide — `panels(spec) -> list[Panel]` (placement), `cut_parts(spec) -> list[Part]`,
  `validate(spec) -> list[Issue]`, `joinery_ops(spec) -> list[JoineryOp]`, and an
  optional `assembly(spec)`. A `register(kind, impl)` table keyed by the
  `dispatch` kind.
- Move the existing cabinet and table bodies behind two implementations
  (`CabinetFurniture`, `TableFurniture`) with **no behaviour change** — pure
  extract-and-register. The stage functions become thin dispatchers:
  `panel_layout` → `registry[spec_kind(spec)].panels(spec)`.
- Extend `tests/test_extensibility.py`: a dummy leaf type registered in the test
  must flow through validate / cutlist / panel_layout / estimate / finishing with
  **zero stage edits** (mirroring the existing group-subclass test).

**Files:** new `furniture.py`; refactor `geometry.py`, `cutlist.py`,
`validator.py`, `joinery.py`, `assembly_steps.py`, `dispatch.py`.
**Risk:** medium (touches core), but fully covered by the existing golden tests
(`tests/test_golden.py`, `golden_specs.py`) — they pin current output byte-for-byte,
so the refactor is correct iff goldens stay green.

---

## H1 — Furniture types for the home shop

**Why.** Today the modellable world is cabinets (7 variants) + a table. A
hobbyist's project list is beds, benches/stools, blanket & tool chests, wall
shelves, and frames. This is the single highest-impact addition.

**Approach.** Each new type is a `LeafFurniture` (post-H0): a spec dataclass in
`dsl.py` (with `from_dict`/`to_dict` + imperial-on-load like `TableSpec`), a
`dispatch` kind, an implementation registered in `furniture.py`, a
`spec_from_dict` route, a `DSL_SCHEMA_HINT` block, and tests. The group/critic/
estimator/finishing/cost layers then work for free off the cut list + panels.

Ship in impact order; **reuse existing primitives** so each is small:

1. **Wall shelf / floating shelf** *(S)* — a board + cleat or brackets; optional
   gallery rail. Trivial geometry; proves the H0 path end-to-end. Hardware: a
   French cleat or hidden-bracket entry in `hardware.py`.
2. **Box / chest** *(M)* — six-board or dovetailed box + lid; reuses the drawer-
   box corner joints (`CornerJoint`: dovetail/box/locking-rabbet, already in the
   DSL) and adds lid hinges + a till. Strong fit with the tooling work (dovetail
   feasibility already modelled).
3. **Bench / stool** *(M)* — seat + 4 legs + aprons **+ stretchers**. Largely a
   `TableSpec` superset; consider a shared `LeggedSpec` base (top/legs/aprons)
   that table and bench both extend, adding stretchers + an angled-leg (splay)
   option. Joinery: mortise-tenon / Domino (leg-apron logic already exists in
   `joinery._table_joinery`).
4. **Bed** *(M–L)* — headboard + footboard (frame-and-panel, which the door
   engine already builds) + side rails joined by **bed-bolt / knock-down**
   hardware + a slat deck. New hardware entries; frame-and-panel reused from
   `cutlist._add_door_parts`.
5. **Frame** *(S)* — picture/mirror frame: 4 mitered or cope-and-stick rails +
   a rabbet for glass/backer. Reuses the rail-and-stile joinery.

**Explicit non-goal:** chairs. Compound seat/back angles, steam-bending and
ergonomic curves are a different engine; document as out of scope so the DSL
stays honest about what it can build.

**Files per type:** `dsl.py` (+spec, +schema hint, +`spec_from_dict` route),
`dispatch.py` (+kind), `furniture.py` (+impl), `hardware.py` (type-specific
hardware), `tests/test_<type>.py`. **No edits** to the generic stages after H0.

---

## H2 — Build from the lumber I already have

**Why.** The estimator nests parts into **standard sheets to compute what to
buy** (`estimator.py` + `packing.py` guillotine). Hobbyists usually start from a
**pile of boards they own** and want: "assign my parts to these boards with a
rip/crosscut plan, tell me what's left over, and what (if anything) I still need
to buy." This is the most-loved feature of tools like CutList Optimizer.

**Plan.**

- **Inventory model:** `StockBoard(length, width, thickness, species, form, qty)`
  in `dsl.py`/`stock.py`; a list of them lives on the request (and optionally the
  `ShopProfile`, since it's shop state, not design state — like `tooling`).
- **`cutplan.py` (new):** group cut-list parts by `(thickness, form, species)`,
  then assign each group's parts to the owned boards using a generalized version
  of `packing.py`'s guillotine packer — **the key refactor is letting the packer
  take an arbitrary bin size** (an owned board) instead of only `STANDARD_SHEET`.
  Grain-aware (a grained part's length runs with the board length, reusing the
  `Grain` handling already in nesting). Output: per-board layout (placed parts +
  offcuts + yield %), a **shortfall list** (parts that didn't fit → fall back to
  the buy-it estimate), and a kerf-aware cut sequence.
- **Outputs:** a "cut from your stock" report (`report.py`), one DXF/SVG layout
  **per board** (`dxf.py`/`drawings.py` already draw nested rectangles + labels),
  a service `cutplan` section, a web **From stock** tab, and CLI
  `--from-stock boards.json`.
- **Tests:** `tests/test_cutplan.py` — assignment correctness, grain alignment,
  kerf accounting, the shortfall path, and a board that's too small.

**Reuse:** `packing.py` (guillotine), `estimator` grain/grouping, `dxf`/`drawings`
nesting renderers. **Risk:** medium; the packer generalization is the crux.

---

## H3 — Build plan: skill level + realistic, method-aware time

**Why.** `estimator.py`'s labour model is a flat rate (base + per-part + per-door
+ per-drawer). It can't tell that **hand-cut dovetails take ~8× a Domino**, and it
offers no difficulty signal. Now that the **tooling inventory** knows which tool
makes each joint, time can be derived from the *actual method*.

**Plan.** New `planning.py` (pure math):

- **Skill rating** — `skill(spec) -> {level, drivers}` from joinery (hand M&T /
  hand dovetails ⇒ *advanced*), part count, glue-up count, finishing, and tight
  tolerances. `level ∈ {beginner, intermediate, advanced}` with the specific
  reasons listed.
- **Method-aware time** — a per-operation time table keyed by **(operation,
  tool)** using the same `tooling.JOINT_WAYS` map: the time for a joint depends on
  which owned tool would make it (hand vs. jig vs. machine). `build_time(spec,
  tooling) -> hours_by_phase` over `{mill, joinery, assembly/glue-up, finish,
  hardware}`, plus a total and the dominant drivers.
- **Wire in:** replace `estimator`'s flat labour with `planning.build_time` (keep
  the flat model as the fallback when no tooling is given, so existing quotes are
  unchanged). Surface skill + the phase breakdown on the web **Build steps** /
  **Cost** tabs and in the CLI report.
- **Tests:** `tests/test_planning.py` — hand-tool joinery costs more time than the
  jig/machine path for the *same* spec; skill escalates with hand joinery.

**Depends on:** the tooling work (✓) and ideally H5 (species hardness nudges some
operation times). **Risk:** low; additive and gated behind tooling presence.

---

## H4 — Finishing depth + glue-up / clamping checklist

**Why.** `finishing.py` is generic (grits + coats); `assembly_steps.py` lists
sub-assembly steps but no **dry-fit, square-check, or clamping** guidance — the
parts hobbyists most often get wrong.

**Plan.**

- **Per-species finishing notes** — extend `finishing.py` with advice keyed by
  species (from H5): blotch-prone woods (pine, cherry, maple) → conditioner;
  oily woods (walnut, teak, rosewood) → solvent-wipe before glue/finish;
  open-pore woods (oak, ash, walnut) → grain filler for a glass finish; plus
  drying/recoat windows per finish type. Surfaced on the existing finishing
  schedule.
- **Glue-up & clamping** — in `assembly_steps.py`, for every *glued* sub-assembly
  emit: a **dry-fit** step, **"check diagonals for square,"** an **open-time**
  caution (PVA ≈ 5–10 min), the existing **don't-glue-cross-grain-rigidly** rule
  (already an engineering check), and a **clamp schedule** — count + length of
  clamps from the panel dimensions (~1 clamp / 150–200 mm of joint), which also
  feeds the tool/shopping list (and the `tooling` checklist as a "clamps" need).
- **Tests:** `tests/test_finishing.py` (species notes), `tests/test_assembly_steps.py`
  (a glue step gains dry-fit + clamp count; a butt-jointed panel warns on
  cross-grain).

**Depends on:** H5. **Risk:** low; pure data + text.

---

## H5 — Wood-species database (the data behind the label)

**Why.** `species` is free text; `engineering.MODULUS_MPA` hardcodes stiffness for
a handful of woods; movement is one global flatsawn/quartersawn constant
(`engineering.MOVEMENT_*`); finishing knows nothing about species. One real table
unblocks H3, H4, and better engineering.

**Plan.** New `species.py` — a table of common woods with: **Janka** hardness,
**modulus E**, **movement coefficient** (radial/tangential, or a per-species
flatsawn/quarter %), **density**, **workability** + **finishing** notes, and a
rough **$/bd-ft**. Then rewire the existing consumers to read it:

- `engineering.modulus_for` → `species.modulus(name)` (move the hardcoded map in).
- `engineering.seasonal_movement` → species-specific coefficient instead of the
  single global constant (keeps the flatsawn/quarter factor as the fallback).
- `estimator` default lumber price per species → `species` `$/bd-ft`.
- `finishing` (H4) and `planning` (H3, hardness nudges hand-tool time) read it.
- `validator` gains species-aware advisories (e.g. "maple blotches — condition
  before stain"); the web gets a small **species reference** + autofill selector.
- **Tests:** `tests/test_species.py` (lookups, fallbacks); update
  `tests/test_engineering.py` to assert species-specific movement.

**Risk:** low; pure data, but **do it early** — it's a dependency for H3/H4.

---

## H6 — Smaller wins (independent, S each)

- **SketchUp-friendly export.** Native `.skp` needs the proprietary SDK — out of
  scope. Practical path: add **Collada `.dae`** (and keep glTF) via `trimesh` in
  `exporters.py`; SketchUp imports DAE/STL/glTF directly. Document that **STEP**
  already imports into Fusion 360 / Onshape. New download button + `tests/test_export_cad.py` case.
- **Per-part export & parts sheet.** The web already explodes by sub-assembly
  (`model_sections` + explode factor). Add **per-part STEP/STL** export and a
  printable **parts thumbnail sheet** (`report.py`) so each part can be made or
  rearranged independently.
- **1:1 templates.** For tapers, the diagonal-corner face, splayed legs and frame
  profiles, emit a **full-size tiled PDF** template from the existing `drawings.py`
  SVG via `reportlab` page-tiling — print, spray-glue, cut to the line.
- **Imperial-first UX.** A per-shop **default unit** on `ShopProfile`; default the
  web/CLI to fractional inches when set (the engine stays mm-native — display only,
  the layer already exists in `units.py`).

---

## Suggested sequence

```
H5 (species data)  ─┐
H0 (leaf refactor) ─┼─▶ H1 (furniture types)  ─▶  H6 wins as filler
                    └─▶ H3 (skill + time)  ─▶  H4 (finishing + glue-up)
H2 (cut from stock) ── independent; schedule whenever
```

1. **H5 + H0** first — small, foundational, unblock the rest (species data; the
   refactor that makes new types cheap).
2. **H1** — the headline user value; ship types one at a time (shelf → box →
   bench → bed → frame), each behind H0 so the generic stages don't change.
3. **H3 → H4** — build-plan depth, leaning on the tooling work and H5.
4. **H2** — the beloved "cut from my boards" feature; independent, slot in anytime.
5. **H6** — small wins as filler between the big phases.

Each phase keeps the suite green (golden tests pin the refactors), adds no CAD
dependency to the core, and ships its own tests that run without an API key or
`build123d`.
