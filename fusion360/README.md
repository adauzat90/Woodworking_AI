# Woodworking AI — Fusion 360 add-in (Phase 3)

Import a Woodworking AI spec (the same JSON the CLI and web app use) into
Fusion 360 as **native geometry**, plus a cut list and a 32 mm drilling
schedule — with **no build123d / OpenCascade** inside Fusion. Or just **describe
the furniture in plain language** and let Claude write the spec (no SDK needed).

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

It adds **two** buttons to the **Solid → Create** panel:

- **Design with Woodworking AI** — type a plain-language description; Claude
  writes a spec, the project's validator + geometry critic check and repair it,
  and it's built as native geometry (see [AI design](#ai-design-phase-3)).
- **Import Woodworking AI Spec** — build from a spec `.json` you already have.

### Import Woodworking AI Spec

1. A dialog lets you pick a spec `.json` and choose options (all default on):
   - **Cut joinery & bores** — machine-honest dados/rabbets/grooves and bores,
     cut from the project's own joinery + drilling schedules (the same numbers
     as the setup sheets), instead of plain slabs.
   - **Component per subassembly** — each buildable unit (Carcass, Doors, Drawer
     box, Countertop…) becomes its own Fusion component for a real assembly tree.
   - **Write cut list + drilling CSV**.
2. It validates the spec with the project's own validator (errors are shown; you
   can build anyway).
3. It compiles the spec to native Fusion bodies — one named `BRepBody` per panel
   (labelled `Subassembly · Panel`), built inside a single `BaseFeature` timeline
   entry per component.
4. It writes the spec's primary dimensions (width/height/depth, sheet
   thicknesses) as Fusion **user parameters** (reference — see below).
5. It writes `<spec>_cutlist.csv` and `<spec>_drilling.csv` next to the spec.

### AI design (Phase 3)

**Design with Woodworking AI** turns a description into geometry:

1. Type a request (e.g. *"36 inch sink base, two shaker doors, soft-close, one
   shelf"*) and pick the same build options, plus **Run geometry critic** and
   **Save spec + cut list**.
2. Claude writes a spec; the project's **validator** and (CAD-free) **geometry
   critic** check it and feed any problem back for repair — the same
   execute-and-verify loop the CLI uses — looping until it's sound.
3. The result is built as native geometry, and (if chosen) the generated spec
   `.json` is saved so you can version, tweak, and re-import it.

This talks to the Claude API through a **pure-`urllib` client**
([`anthropic_client.py`](anthropic_client.py)) — no `anthropic` SDK and no
native wheels, which is what makes it work inside Fusion's Python. It honours the
standard `HTTPS_PROXY` environment, so it works behind a corporate proxy.

#### API key

The AI command needs an Anthropic API key, found in this order:

1. the `ANTHROPIC_API_KEY` environment variable;
2. `anthropic_key.txt` next to `WoodworkingAI.py`;
3. `~/.woodai/anthropic_key`.

The key is never shown in the dialog. `anthropic_key.txt` is git-ignored. Pick
the model with the **Model** box (blank = the project default, currently
`claude-opus-4-8`) or the `WOODAI_MODEL` env var.

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

**Scripted (Windows, recommended):** [`install.ps1`](install.ps1) wires the
add-in into Fusion's per-user Add-Ins folder for you and verifies the package
resolves. By default it creates a directory **junction** (no admin needed) back
to this `fusion360` folder, so edits in the repo are picked up on the add-in's
next *Run* — nothing to re-copy.

```powershell
powershell -ExecutionPolicy Bypass -File fusion360\install.ps1            # live junction to this repo
powershell -ExecutionPolicy Bypass -File fusion360\install.ps1 -Copy      # self-contained copy (repo not needed after)
powershell -ExecutionPolicy Bypass -File fusion360\install.ps1 -Uninstall # remove it
```

Then, in Fusion: **Utilities → Add-Ins → Scripts and Add-Ins** (`Shift+S`),
select **Woodworking AI** on the **Add-Ins** tab, and click **Run** (tick *Run
on Startup* to keep it loaded).

**Manual, in-repo:** the add-in finds `../src/woodworking_ai` automatically.

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
2. Either **Solid → Create → Design with Woodworking AI** (describe it), or
   **Import Woodworking AI Spec** and pick a spec — e.g.
   [`examples/sink_base.json`](examples/sink_base.json).
3. The geometry appears as a new component; the cut list and drilling CSVs land
   beside the spec file (for a designed piece, wherever you save it).

You can also generate specs with the CLI or web app, or hand-write them — the
format is the [design language](../README.md#the-design-language-example).
Projects (multi-cabinet runs), tables, dressers, bookcases, and corner cabinets
all work, because `panel_layout()` already handles them.

## Remote control — the folder bridge

Normally you drive the add-in by clicking its buttons. The **folder bridge**
lets an external script or agent drive it instead, **without opening a network
port**: you drop a request `.json` into a watched *inbox* and the add-in builds
it in the active Design document, writing a result `.json` to an *outbox*.

**Why a folder, not a socket:** Fusion's API is single-threaded and not
thread-safe. The bridge's background poller only does file I/O; when it sees a
new request it fires a Fusion **custom event**, and the build runs on Fusion's
main thread where `adsk` calls are safe. (See [`bridge.py`](bridge.py).)

**Start it** one of two ways:

- Click **Solid → Create → Woodworking AI: Auto-build bridge** (click again to
  stop); or
- set `WOODAI_FUSION_BRIDGE=1` before launching Fusion so it auto-starts when
  the add-in loads.

The drop directory is `%WOODAI_FUSION_DROP%` or `~/.woodai/fusion_drop`:

```
<drop>/inbox/      # write requests here (atomic rename)
<drop>/outbox/     # <name>.result.json (+ saved spec / CSV reports)
<drop>/processed/  # requests already built
<drop>/status.json, heartbeat.json   # liveness — refreshed every second
```

**Request** = an envelope or a bare spec:

```jsonc
{ "spec": { /* a Woodworking AI spec */ },
  "options": { "machined": true, "by_subassembly": true, "write_reports": false } }
// or, to have Claude design it (needs an Anthropic API key):
{ "prompt": "36 inch sink base, two shaker doors, soft-close, one shelf",
  "options": { "run_critic": true } }
```

**Drive it** from any Python with the stdlib-only client
([`bridge_client.py`](bridge_client.py)) — no Fusion, no `woodworking_ai` needed:

```bash
python bridge_client.py status                       # is the in-Fusion bridge alive?
python bridge_client.py import examples/sink_base.json --reports --wait 120
python bridge_client.py design "small 3-shelf oak bookcase" --wait 180
```

or in-process: `submit(request)`, `wait_result(name)`, `submit_and_wait(request)`.

## Scope (Phase 3)

- **In:** natural-language design (Claude → validate → critic → repair) over a
  pure-`urllib` client, no SDK; all spec kinds the layout supports; through
  cut-outs (sink/cooktop); rotated panels (diagonal-corner door); validation;
  **machined joinery + bores** (degrade-safe per panel); **per-subassembly
  components**; spec dimensions as **user parameters**; cut list + drilling
  export.
- **Not built inside Fusion:** build123d STEP/STL/GLB export (Fusion exports
  natively) and the matplotlib render-based visual critic (Fusion is the
  viewport). The analytical, CAD-free critic runs. See the phase plan in
  [`docs/FUSION360.md`](../docs/FUSION360.md).

## Files

| File | Role |
|---|---|
| `install.ps1` | One-command install/uninstall into Fusion's Add-Ins folder (junction or copy) |
| `WoodworkingAI.manifest` | Add-in manifest (id, name, entry point) |
| `WoodworkingAI.py` | Entry point — both commands, dialogs, validate, report writing |
| `adapter.py` | `PanelBox` layout → native Fusion `BRepBody` solids (the build123d replacement) |
| `anthropic_client.py` | Pure-`urllib` Claude Messages client (the `anthropic` SDK replacement) |
| `bridge.py` | Folder-bridge watcher — polls the inbox, builds on Fusion's main thread via a custom event |
| `bridge_core.py` | Pure (Fusion-free) request parsing + validation flattening — unit-testable |
| `bridge_client.py` | Stdlib-only shell client: drop a request, wait for the result |
| `examples/sink_base.json` | A sample spec to import |
