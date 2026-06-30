# Bringing Woodworking AI into Fusion 360

**Verdict: yes, and the architecture makes it a clean fit.** A working Phase-1
add-in lives in [`fusion360/`](../fusion360/). This document records *why* it
fits, what carries over for free, the real caveats, and the phase plan.

## The key insight

Most of the effort in porting a CAD tool is the geometry kernel. Here that work
**disappears**, because the part that's hard to port is the part we throw away.

The geometry source of truth is
[`geometry.panel_layout()`](../src/woodworking_ai/geometry.py): pure-Python math
that returns a list of `PanelBox`es — each just a `size` (w, d, h), a `center`,
and an optional `rot_z` about the vertical axis, in a documented shared frame.
[`builder.py`](../src/woodworking_ai/builder.py) is the *only* module that needs
build123d / OpenCascade, and all it does is turn each `PanelBox` into a `Box`
solid, translate it, and boolean-subtract rabbets/dados/openings
(`builder.py:248`).

Those operations map one-to-one onto Fusion's API. So inside Fusion we **don't
port build123d at all** — we re-target the box-emitting step to Fusion's
`TemporaryBRepManager`, and reuse everything upstream and downstream unchanged.

## Why it ports cleanly

**1. The geometry is data, not CAD calls.** `panel_layout()` produces boxes;
the adapter ([`fusion360/adapter.py`](../fusion360/adapter.py)) maps each to a
Fusion `OrientedBoundingBox3D` → `createBox`, with through-`openings`
boolean-subtracted. A `rot_z` becomes the box's length/width direction vectors.
The only frame conversion is millimetre → centimetre (Fusion's internal unit):
`mm / 10`.

**2. The core has zero third-party dependencies.** `pyproject.toml` declares
`dependencies = []`. The DSL, validator, cut list, drilling schedule, hardware
BOM, and cost estimator are all standard-library Python (3.11+ for `StrEnum`).
Fusion 360 ships an embedded CPython 3.12, so the package is `import`-able with
**no `pip install` step** — the usual wall for Fusion add-ins (you can't drop
native wheels like OCP into Fusion's interpreter) never comes up, because the
geometry side is exactly what we replaced.

So the add-in is essentially:

```
spec JSON ─▶ validator (as-is) ─▶ panel_layout() (as-is)
          ─▶ adapter: PanelBox → adsk.fusion bodies   ← the only new geometry code
          ─▶ cut list / drilling / BOM (as-is)
```

## What carries over

| Component | In a Fusion add-in |
|---|---|
| DSL, validator, cut list, drilling, hardware BOM, cost estimate | **Drop-in** — pure Python, no deps |
| `panel_layout` geometry (boxes + openings + rotation) | **Drop-in** as data; one adapter module to Fusion bodies |
| `builder.py` (build123d) | **Replaced** by the adapter — OpenCascade never loads in Fusion |
| STEP / STL / GLB export | **Dropped** — Fusion exports natively once bodies exist |
| Designer / Critic AI agents (`anthropic`) | Workable, but harder — needs an HTTPS client that runs inside Fusion (Phase 2) |
| Web app / FastAPI / matplotlib render | Not relevant — Fusion provides the viewport |

## The real caveats

- **You rebuild the compiler, not reuse it.** The `PanelBox → adsk.fusion`
  adapter is new code. It's small (boxes + boolean cuts), but it's the one
  genuinely new module, plus the command/UI plumbing.
- **Native wheels can't ride along.** build123d/OCP and `anthropic`'s native
  bits aren't installable into Fusion's interpreter. The geometry side dodges
  this by design; the AI designer would need a pure-`urllib`/`http.client`
  client to keep working.
- **Static bodies first.** Phase 1 produces real, editable bodies but not a
  parameter-driven timeline. True Fusion *user parameters* (dimensions that
  re-drive the model) is a larger effort — though a natural fit, since the DSL
  fields already *are* the parameters.

## Phase plan

**Phase 1 — done ([`fusion360/`](../fusion360/)).** An add-in that reads a spec
JSON, validates it, builds native Fusion bodies via the adapter, and writes the
cut list + drilling CSV. Zero external dependencies; reuses the project's
pure-Python pipeline verbatim.

**Phase 2 — parametric + machined.**
- Map DSL fields (width/height/depth/reveal/material thicknesses…) to Fusion
  **user parameters**, so the model re-drives when they change.
- Cut real joinery into the solids (dados/rabbets/grooves/bores) by consuming
  the existing joinery + drilling schedules — the analogue of `builder.py`'s
  opt-in `joinery_geometry`.
- Emit each subassembly as its own component/occurrence for a richer browser
  tree and assembly structure.

**Phase 3 — the AI designer inside Fusion.** A natural-language box that calls
the Claude designer over a pure-Python HTTPS client (no native deps), runs the
same validate → repair loop, then builds — bringing the full
language-to-geometry agent loop into Fusion.

## Verifying the adapter without Fusion

The reused pipeline runs headlessly (it's the project's normal test path). The
adapter's geometry math (mm→cm, rotation vectors, opening placement, boolean
subtraction) is checked by stubbing the `adsk` API — no Fusion install needed —
in [`tests/test_fusion_adapter.py`](../tests/test_fusion_adapter.py).
