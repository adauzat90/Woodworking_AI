# Human testing checklist — `claude/woodworking-app-review-bqmbe7`

Everything in this branch passes **943 automated tests** (pure-math core, cut
lists, validators, geometry envelopes, the web API, PDF generation). Those do
**not** need re-checking. What's listed below is the part a machine can't verify
headlessly: **browser rendering, real 3D/CAD output, physical print scale, and
the paid AI path.** Work top-to-bottom when you're next at a computer.

## How to start the app

```bash
pip install -e ".[all]"
python -m woodworking_ai.web        # then open http://127.0.0.1:8000
```

(Optional, for the AI box: `export ANTHROPIC_API_KEY=sk-...` before launching.)

Legend: ☐ = to test · each item says **what to do** and **what "pass" looks
like**.

---

## A. Web UI — interactions I couldn't verify headlessly

These are new front-end pieces (`src/woodworking_ai/static/index.html`). The
HTML/JS is present and the page serves, but I can't confirm it *renders and
behaves* correctly in a real browser.

- ☐ **Starter gallery (G3).** At the top of the left panel, **"🧰 Start from a
  project"** should show a grid of cards (Bookcase, Base cabinet, Dining table,
  Nightstand, Writing desk, Workbench, Cutting board, Picture frame, Blanket
  chest, Floating shelf, Queen bed, …).
  *Pass:* clicking a card builds that design and the 3D preview + cut list fill
  in. Try one from each category.

- ☐ **Assembly walkthrough (G2a).** Build something with several sub-assemblies
  (e.g. the **Queen bed**, **Nightstand**, or a **Drawer base**). A build-stepper
  bar appears under the 3D model.
  *Pass:* dragging **Build** isolates sub-assemblies one at a time; a caption
  under the model names the step and lists its parts; **▶ Walk** auto-advances
  through the build and pauses on each step (▶ toggles to ⏸). In the **Build
  steps** tab, **👁 Show in 3D** next to a sub-assembly isolates it in the
  preview.

- ☐ **Click-to-edit dimensions (G2b).** With a cabinet/table/nightstand/desk
  built, a small overlay (top-right of the 3D view) shows **W / H / D** with an
  **edit ✎** hint.
  *Pass:* clicking a value prompts for a new number, and the model + cut list
  rebuild at the new size. (Frame/bed/board show the numbers read-only by
  design — confirm they don't offer a broken edit.)

- ☐ **Responsive layout (G5).** Resize the window narrow, or open the URL on
  your phone.
  *Pass:* under ~820px the left panel stacks **above** the preview (no
  side-by-side squeeze), tabs wrap, the gallery goes single-column, and it's
  usable one-handed. Under ~480px the form rows wrap.

- ☐ **Units toggle stays sensible.** Flip **Units** (top-right of the tabs)
  between inches and mm.
  *Pass:* the cut list / reports reformat; the dimension overlay shows the
  matching unit.

## B. 3D model & CAD exports — need a real graphics/CAD environment

The geometry **builds** and its bounding box matches the spec in tests, but the
visual result and downstream CAD compatibility need eyes.

- ☐ **New furniture types render correctly** in the `<model-viewer>` preview:
  **frame, bed, cutting board, nightstand, desk, workbench**. Look for: parts in
  the right places, nothing obviously floating, proportions that look like the
  real piece. (The workbench vise is intentionally *not* drawn — it's in the cut
  list/joinery only.)

- ☐ **Downloads open in real tools.** For a couple of designs, download and open:
  - **STEP** → Fusion 360 / Onshape (B-Rep, the important one).
  - **GLB** → any glTF viewer.
  - **DAE** → SketchUp import.
  - **DXF** → the cut-layout opens in a CAD/CNC program.
  - **STL** → a slicer/mesh viewer.
  *Pass:* the model imports without errors and looks like the preview.

- ☐ **Build-package PDF** (📄 button) and **Purchase order** (🧾) open and read
  cleanly.

## C. Print & 1:1 templates — need paper + a ruler

- ☐ **1:1 template scale (G6a).** Build any design, click **📐 1:1 template**,
  and **print the PDF at 100% / "Actual size" (NOT "fit to page")**. The first
  page is a calibration cover.
  *Pass:* with a ruler, the **100 mm** square measures 100 mm and the **4 in**
  square measures 4 in. If they're off, the printer isn't at 100%. Then check the
  tiled pages tape together at the registration ticks into the full-size part
  outline. **This is the one test that truly needs physical measurement.**

- ☐ **Print stylesheet (G5).** Open a report tab (Cut list / Drilling / Build
  steps), click **🖨 Print** (or Ctrl/Cmd-P).
  *Pass:* the printout is clean black-on-white with ruled tables — no 3D canvas,
  no app chrome, no dark background. This is the page you'd tape to the shop
  wall.

## D. AI designer path — needs `ANTHROPIC_API_KEY` (paid)

Only the parametric path is exercised by tests; the natural-language path calls
the model.

- ☐ **Describe-it box** builds a sensible cabinet/table from a sentence
  (e.g. *"900mm sink base, two shaker doors, soft-close, one shelf"*).

- ☐ **New types via natural language.** Try prompts that should map to the new
  kinds and confirm the AI emits the right `kind` and a buildable spec:
  - *"a walnut picture frame for a 16x20 print"* → `frame`
  - *"a queen platform bed in oak"* → `bed`
  - *"a small nightstand with one drawer"* → `nightstand`
  - *"a maple and walnut end-grain cutting board"* → `cutting_board`
  - *"a heavy workbench with a vise"* → `workbench`
  *Pass:* it builds; if a design is unbuildable the critic-repair loop should
  fix it rather than erroring out. (If the AI ignores a new type, the fix is
  prompt/schema-hint tuning — tell me and I'll adjust.)

## E. Sanity — a woodworker's eye on the new types

Automated tests check the math and that warnings fire; they can't judge whether
the **defaults look like real furniture**. Skim the cut list + proportions for
each new type and flag anything that reads wrong:

- ☐ **Nightstand / desk** — drawer sizes, leg/apron proportions, shelf/modesty
  placement.
- ☐ **Bed** — mattress fit, rail/slat count, post heights; the wide-deck
  "add a centre support" warning on queen/king.
- ☐ **Workbench** — top thickness, dog-hole spacing, lamination count, height.
- ☐ **Cutting board** — strip count/width, food-safe finish + species advisories.
- ☐ **Frame** — rabbet vs. molding thickness, the weak-miter / heavy-mirror
  warnings.

---

## Known follow-ups (not bugs — deferred by design)

- **G2b drag-handles:** dimensions are **click-to-edit** today; true
  drag-to-resize handles on the 3D model were deferred because they need browser
  QA I can't do here.
- **Two PDF content tests skip** unless `pymupdf`/`fitz` is installed (they pass
  where it is) — not a failure, just an optional dependency.

If anything in A–E looks wrong, note the design + what you saw and I'll fix it.
