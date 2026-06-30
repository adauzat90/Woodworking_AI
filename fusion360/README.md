# Woodworking AI — Fusion 360 add-in (Phase 2)

Import a Woodworking AI spec (the same JSON the CLI and web app use) into
Fusion 360 as **native geometry**, plus a cut list and a 32 mm drilling
schedule — with **no build123d / OpenCascade** inside Fusion.

> Why this works: the project's geometry source of truth,
> [`geometry.panel_layout()`](../src/woodworking_ai/geometry.py), is pure-Python
> math that returns axis-aligned `PanelBox`es (size + center + optional
> Z-rotation). build123d is only used downstream to turn those boxes into B-Rep
> solids. This add-in swaps that one backend for Fusion's own API
> ([`adapter.py`](adapter.py)) and reuses the rest of the **zero-dependency**
> package (DSL, validator, cut list, drilling) verbatim. See
> [`docs/FUSION360.md`](../docs/FUSION360.md) for the full feasibility analysis
> and the phase plan.

## What it does

1. Adds an **Import Woodworking AI Spec** button to the **Solid → Create** panel.
2. A dialog lets you pick a spec `.json` and choose options (all default on):
   - **Cut joinery & bores** — machine-honest dados/rabbets/grooves and bores,
     cut from the project's own joinery + drilling schedules (the same numbers
     as the setup sheets), instead of plain slabs.
   - **Component per subassembly** — each buildable unit (Carcass, Doors, Drawer
     box, Countertop…) becomes its own Fusion component for a real assembly tree.
   - **Write cut list + drilling CSV**.
3. It validates the spec with the project's own validator (errors are shown; you
   can build anyway).
4. It compiles the spec to native Fusion bodies — one named `BRepBody` per panel
   (labelled `Subassembly · Panel`), built inside a single `BaseFeature` timeline
   entry per component.
5. It writes the spec's primary dimensions (width/height/depth, sheet
   thicknesses) as Fusion **user parameters** (reference — see below).
6. It writes `<spec>_cutlist.csv` and `<spec>_drilling.csv` next to the spec.

### A note on parameters

The geometry is computed by the project's Python layout (`panel_layout()`), not
by Fusion's constraint solver — the **DSL spec is the parametric model**. So the
user parameters are *reference documentation*: editing one won't re-drive the
bodies. To change the design, edit the spec (or regenerate it with the CLI / web
app) and re-import. This matches the whole project's philosophy: the text spec
is the single, diffable source of truth.

## Install

Fusion's embedded interpreter is CPython 3.12, so the pure-Python
`woodworking_ai` package (it has **zero** third-party dependencies) imports
directly — nothing to `pip install` into Fusion.

**In-repo (simplest):** the add-in finds `../src/woodworking_ai` automatically.

1. **Utilities → Add-Ins → Scripts and Add-Ins** (or press `Shift+S`).
2. On the **Add-Ins** tab, click the green **+** and select this `fusion360`
   folder.
3. Select **Woodworking AI** and click **Run** (tick *Run on Startup* to keep
   it loaded).

**Standalone (outside the repo):** copy the `woodworking_ai` package next to
`WoodworkingAI.py` first (the loader also checks `./woodworking_ai`,
`./vendor/woodworking_ai`, and `./src/woodworking_ai`):

```bash
cp -r ../src/woodworking_ai fusion360/woodworking_ai
```

then add the `fusion360` folder as an add-in as above.

## Use

1. Open or create a **Design** document.
2. **Solid → Create → Import Woodworking AI Spec**.
3. Pick a spec — e.g. [`examples/sink_base.json`](examples/sink_base.json).
4. The geometry appears as a new component; the cut list and drilling CSVs land
   beside the spec file.

Generate specs with the CLI or web app, or hand-write them — the format is the
[design language](../README.md#the-design-language-example). Projects
(multi-cabinet runs), tables, dressers, bookcases, and corner cabinets all work,
because `panel_layout()` already handles them.

## Scope (Phase 2)

- **In:** all spec kinds the layout supports; through cut-outs (sink/cooktop);
  rotated panels (diagonal-corner door); validation; **machined joinery + bores**
  (dados/rabbets/grooves/bores, degrade-safe per panel); **per-subassembly
  components**; spec dimensions as **user parameters**; cut list + drilling
  export.
- **Not yet (Phase 3):** the AI designer agent inside Fusion (needs a pure-Python
  HTTPS client). See the phase plan in
  [`docs/FUSION360.md`](../docs/FUSION360.md).

## Files

| File | Role |
|---|---|
| `WoodworkingAI.manifest` | Add-in manifest (id, name, entry point) |
| `WoodworkingAI.py` | Entry point — command button, file dialog, validate, report writing |
| `adapter.py` | `PanelBox` layout → native Fusion `BRepBody` solids (the build123d replacement) |
| `examples/sink_base.json` | A sample spec to import |
