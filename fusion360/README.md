# Woodworking AI — Fusion 360 add-in (Phase 1)

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
2. You pick a spec `.json` file.
3. It validates the spec with the project's own validator (errors are shown; you
   can build anyway).
4. It compiles the spec to native Fusion bodies — one named `BRepBody` per panel
   (labelled `Subassembly · Panel`), grouped in a new component named after the
   spec, built inside a single `BaseFeature` timeline entry.
5. It writes `<spec>_cutlist.csv` and `<spec>_drilling.csv` next to the spec.

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

## Scope (Phase 1)

- **In:** all spec kinds the layout supports; through cut-outs (sink/cooktop);
  rotated panels (diagonal-corner door); validation; cut list + drilling export.
- **Not yet:** Fusion *user parameters* driving the timeline (bodies are static
  for now — Phase 2); machined joinery cuts (dados/rabbets/bores) in the solids
  (the CLI's opt-in `joinery_geometry`); the AI designer agent (needs an HTTPS
  client that works inside Fusion). See the phase plan in
  [`docs/FUSION360.md`](../docs/FUSION360.md).

## Files

| File | Role |
|---|---|
| `WoodworkingAI.manifest` | Add-in manifest (id, name, entry point) |
| `WoodworkingAI.py` | Entry point — command button, file dialog, validate, report writing |
| `adapter.py` | `PanelBox` layout → native Fusion `BRepBody` solids (the build123d replacement) |
| `examples/sink_base.json` | A sample spec to import |
