# Woodworking AI — Architecture & Design

> An application that designs cabinets and furniture using AI agents that write
> and refine a **parametric design language**, then compile that language into
> real, machinable 3D geometry, cut lists, and hardware schedules.

---

## 1. The core idea

Most "AI + 3D" tools try to make a model *generate a mesh directly*. That fails
for furniture, because furniture has to be **buildable**: square panels, real
sheet-goods thicknesses, joinery that actually fits, and a cut list a shop can
take to a saw or CNC.

The pattern that works — proven by [Zoo's **Zookeeper**](https://zoo.dev/research/zookeeper)
agent and academic systems like [Seek-CAD](https://arxiv.org/pdf/2505.17702) — is:

> **The AI agent does not draw the furniture. It writes _code_ in a parametric
> design language, executes that code to build real geometry, inspects the
> result, and repairs its own code until the design is valid.**

LLMs are far stronger at producing and debugging *language* than at producing
binary geometry. So we make CAD into a language the agent can read, write, and
verify. The design's source of truth is text — versionable, diffable, and
explainable — exactly like source code.

### Prior art this design draws from

| Tool | Premise | What we borrow |
|---|---|---|
| [Zookeeper / Zoo](https://zoo.dev/research/zookeeper) | Conversational agent writes **KCL** (a CAD language), executes & debugs it, inspects mass/volume/snapshots | The agent-writes-code + execute-verify-repair loop; B-Rep output |
| [KCL](https://zoo.dev/research/introducing-kcl) | A programming language whose source of truth is text, not binary | "Design as code" — store geometry as a language so LLMs understand it |
| [Prompt2CAD](https://www.3dprintingjournal.com/p/prompt2cad-ai-designs-furniture-but) | Text → parametric furniture with adjustable sliders; exports STEP/DXF/STL/GLB | Parameters as first-class knobs; multi-format export |
| [Flatma](https://flatma.com/en/articles/ai-3d-model-generator/) | AI custom cabinets, each design ships a **material list + cut list** | Construction-ready outputs, not just a render |
| [PolyBoard](https://wooddesigner.org/polyboard-software-tools/) | Parametric cabinet software → cut lists, CNC files, pricing | What cabinetmakers actually need downstream |
| [CadQuery](https://github.com/cadquery/cadquery) / [build123d](https://build123d.readthedocs.io/en/latest/external.html) | Python, B-Rep, parametric, STEP/DXF export | Our geometry engine (see §3) |

---

## 2. The "form of programming language": a furniture DSL

We do **not** ask the LLM to write raw build123d Python (powerful, but easy to
get subtly wrong and hard to validate). Instead we define a small, declarative
**furniture description language** — a typed spec the agent emits as JSON. This
is the "programming language" at the heart of the app.

```jsonc
{
  "type": "base_cabinet",
  "units": "mm",
  "width": 600, "height": 720, "depth": 560,
  "material": { "carcass": 18, "back": 6, "door": 18 },   // sheet thicknesses
  "construction": "frameless",            // frameless (Euro) | face_frame
  "back": "rabbeted",                     // rabbeted | applied | grooved
  "toe_kick": { "height": 100, "setback": 50 },
  "shelves": 1,
  "doors": 2,
  "drawers": [ { "front_height": 140 } ],
  "joinery": "dado",                      // dado | dowel | domino | screw
  "reveal": 3,                            // gap around overlay doors/drawers
  "edge_banding": true
}
```

Why a DSL instead of raw CAD code:

1. **Validatable.** Every field has a type and a range. The agent's output is
   checked *before* we attempt geometry — most errors are caught for free.
2. **Compilable.** One deterministic compiler turns the spec into geometry,
   so the geometry is always correct *given a valid spec*. The agent only has to
   get the spec right, not the trigonometry.
3. **Explainable & editable.** A human (or another agent) can read and tweak
   the spec. It diffs cleanly in git.
4. **Cut-list native.** Because parts are explicit in the spec, the cut list and
   hardware schedule fall out of the same data — no second source of truth.

The DSL is intentionally layered: it can grow from cabinets to tables, dressers,
and built-ins by adding spec types and compiler rules, without changing agents.

---

## 3. Engine recommendation: **build123d**

Recommended after weighing the options for a **furniture/woodworking** target:

| Engine | Kernel / output | Verdict for this app |
|---|---|---|
| **build123d** ✅ | OpenCascade B-Rep, Python, STEP/DXF/STL | **Chosen.** Modern, clean Python the LLM writes well; true B-Rep → STEP for CNC and DXF for nesting/cut layouts; runs locally so the verify loop is free and offline. |
| CadQuery | Same kernel, older fluent API | Great fallback; build123d is its cleaner successor. We keep our compiler engine-swappable. |
| KCL (Zoo) | Hosted B-Rep + ML API | Powerful but a third-party dependency and less control over the verify loop. Good future export target. |
| OpenSCAD | Own DSL, **mesh** output | Rejected: mesh-only means no clean STEP/DXF, poor fit for CNC cabinetry. |

build123d gives us **B-Rep** (boundary representation), which is what lets us
export clean **STEP** (machining/CNC), **DXF** (2D cut layouts / nesting),
plus **STL/GLB** for preview/AR — the same multi-format story as Prompt2CAD.

The compiler is isolated behind an interface so a future KCL or CadQuery backend
can be added without touching the DSL or the agents.

---

## 4. The agent loop

```
            ┌─────────────────────────────────────────────────────────┐
            │                                                         │
  User NL   ▼                                                         │
 "36in base   ┌──────────────┐   DSL spec    ┌──────────────┐         │
  cabinet,  │  Designer     │ ────────────▶ │  Validator    │         │
  2 doors,  │  agent (LLM)  │               │ (types,ranges,│         │
  shaker"   │  NL → DSL     │ ◀──────────── │  sanity rules)│         │
            └──────────────┘  repair prompt └──────┬───────┘         │
                                                   │ valid spec      │
                                                   ▼                 │
                                            ┌──────────────┐         │
                                            │  Compiler     │        │
                                            │ DSL→build123d │        │
                                            │  B-Rep model  │        │
                                            └──────┬───────┘         │
                                  build error /    │  geometry       │
                                  interference     ▼                 │
                                            ┌──────────────┐         │
                                            │  Critic       │ ───────┘
                                            │ measure dims, │  feedback
                                            │ check fit vs  │  to agent
                                            │ spec, render  │
                                            └──────┬───────┘
                                                   │ pass
                                                   ▼
                       Outputs: GLB preview · STEP (CNC) · DXF (cut layout)
                                · cut list (CSV) · hardware schedule
```

The decisive feature — same as Zookeeper and Seek-CAD — is the
**execute-and-verify loop**: the agent's output is *run*, the resulting geometry
is *measured*, and discrepancies are fed back so the agent self-corrects. This
is what separates a buildable design from a plausible hallucination.

### Agents

- **Designer** — Natural language → DSL spec. Few-shot prompted with the DSL
  schema and worked examples. The only agent that must "understand" furniture.
- **Validator** — *Not* an LLM. Deterministic schema + woodworking sanity rules
  (e.g. shelf depth ≤ carcass depth − back, door reveal ≥ 0, drawer box clears
  slides). Cheap, fast, catches most errors before geometry.
- **Critic** *(implemented)* — Verifies the *built geometry*, in two modes that
  mirror Zookeeper's "computational tools **and** visual snapshots":
  - **Computational** (default, no CAD dependency): reconstructs every panel
    from the shared layout, checks the overall envelope against the spec,
    detects part-to-part interferences (positive-volume collisions), and reports
    clear opening, front coverage, and sheet area. On any error it emits a
    structured repair note the Designer loop feeds back. During development it
    caught a genuine bug — the rear top rail intersecting the back panel —
    before any geometry was exported. Optionally cross-checks the real B-Rep.
  - **Render-based** (opt-in): renders front/side/isometric snapshots from the
    same layout (matplotlib, headless — no GPU/display), then asks a
    vision-capable Claude model to inspect them for problems measurement can't
    see (lopsided or missing fronts, uneven gaps, off proportions). Its findings
    return as `visual` warnings — a second opinion, not a hard gate — and the
    review degrades gracefully when matplotlib or an API key is absent.
- *(future)* **Estimator** — sheet-goods nesting, board-feet, cost.

> **Single source of truth for geometry.** Panel placement lives in one place,
> `geometry.py::panel_layout`, consumed by *both* the compiler (`builder.py`)
> and the Critic. The model the Critic measures is therefore always the model
> the compiler builds — they cannot drift apart.

---

## 5. Repository layout

```
src/woodworking_ai/
  dsl.py          # The furniture language: typed spec dataclasses + JSON (de)serialize
  validator.py    # Schema + woodworking sanity rules (pure Python, no CAD dep)
  cutlist.py      # Spec → parts list + hardware schedule (pure math, no CAD dep)
  geometry.py     # panel_layout(): the single source of truth for panel placement
  builder.py      # Spec → build123d B-Rep geometry (the compiler)
  render.py       # Headless front/side/iso snapshots (matplotlib, no GPU)
  estimator.py    # Sheet nesting + cost estimate (pure math, no CAD dep)
  drilling.py     # 32mm drilling schedule: shelf pins, hinge bores, slide lines
  dxf.py          # DXF cut-layout nest diagram (pure text, no CAD dep)
  exporters.py    # Geometry → STEP / STL / GLB / DXF ; cut list → CSV
  service.py      # Assemble a full design bundle (shared by web/CLI)
  web.py          # FastAPI backend + SPA (live GLB, cut list, cost, drilling)
  static/         # The single-page front end
  agents/
    llm.py        # Anthropic client wrapper (Claude), incl. vision
    designer.py   # NL → DSL with validate-and-repair (+ critic) loop
    critic.py     # Computational + render-based (visual) verification
  cli.py          # `woodai design "..."` entry point
examples/
  base_cabinet.py # Build a cabinet straight from a DSL spec (no LLM needed)
tests/
  test_cutlist.py # Pure-math tests that run without build123d or an API key
```

Design choice: **cutlist.py and validator.py have no CAD dependency**, so the
business-critical logic (parts, dimensions, hardware, sanity) runs anywhere,
fast, and is fully unit-tested. The heavy build123d/OpenCascade dependency is
needed only to render and export 3D geometry.

---

## 6. Roadmap

1. ✅ **MVP:** frameless base cabinet — DSL, validator, cut list, build123d
   geometry, STEP/STL export, an LLM designer agent, and the Critic.
2. ✅ **Cabinet types & construction:** wall and tall/pantry cabinets; face-frame
   construction (stiles/rails + inset fronts) alongside frameless overlay.
3. ✅ **Critic:** envelope + AABB interference, render-based visual review, and
   opt-in true B-Rep boolean interference. Next: multi-angle / textured renders.
4. ✅ **Estimator:** guillotine sheet nesting → sheet count + utilization, and a
   material/hardware/edge-banding/labour cost breakdown.
5. ✅ **Hardened engine:** real drawer boxes + false fronts, center mullions, a
   32 mm-system drilling schedule (pins/hinges/slides), a DXF cut-layout, a
   verified STEP/STL/GLB B-Rep path, and **corner cabinets** — blind corners
   (offset opening + filler) and diagonal corners (angled door via Z-rotated
   panels, with trim-to-fit blanks excluded from interference).
6. ✅ **Casegoods beyond cabinets:** bookcases and dressers (cabinet engine), and
   a polymorphic **table** type (top/legs/aprons) — `panel_layout`,
   `generate_cutlist`, `validate`, and the Critic now dispatch on the spec type,
   so new furniture plugs into the whole pipeline. `spec_from_dict` routes a
   payload to the right spec.
7. ✅ **Web UI:** FastAPI backend + single-page front end with a live GLB 3D
   preview (`<model-viewer>`), parametric form, NL design box, in-browser cut
   list / cost / drilling, **live update**, **downloads** (STEP/STL/GLB/DXF/CSV),
   **share links**, and a **saved-design library** (Convex or localStorage).
   Next: KCL export for Zoo interop.
8. ✅ **Imperial I/O + language hardening:** a millimetre-native engine with an
   imperial **display layer** (fractional inches to 1/16″) *and* imperial
   **input** (`"units": "in"` converts to mm in `from_dict`); the designer now
   emits cabinets **or** tables (routed by `spec_from_dict`); the LLM schema hint
   is **generated from the enums** so it can't drift; drawer/table string fields
   are promoted to `StrEnum`s; and a **Project/assembly** layer aggregates a run
   of placed components into one validation, cut list, quote, **and one
   assembled 3D model** — `geometry.project_layout` places every component's
   panels in the run frame (the same single-source-of-truth pattern), so the
   Critic checks cabinet-to-cabinet collisions and `build_project` exports the
   whole run as one GLB/STEP/DXF. **L-/U-shaped runs** are supported: components
   are anchored by a front-left corner + wall angle (`place_run` lays a run
   along a wall), and overlaps use oriented 2D footprints (SAT), so the inner
   corner where two perpendicular runs meet is verified. See `docs/DSL_REVIEW.md`
   for the review that drove this.

---

## 7. Sources

- Zoo, *Zookeeper: The Conversational CAD Agent* — https://zoo.dev/research/zookeeper
- Zoo, *KCL: A Programming Language for Parametric CAD* — https://zoo.dev/research/introducing-kcl
- *Prompt2CAD* — https://www.3dprintingjournal.com/p/prompt2cad-ai-designs-furniture-but
- Flatma, *AI 3D Model Generator* — https://flatma.com/en/articles/ai-3d-model-generator/
- *Seek-CAD: Self-refined Generative Modeling for 3D Parametric CAD* — https://arxiv.org/pdf/2505.17702
- CadQuery — https://github.com/cadquery/cadquery
- build123d — https://build123d.readthedocs.io/en/latest/external.html
- PolyBoard — https://wooddesigner.org/polyboard-software-tools/
