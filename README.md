# Woodworking AI

Design cabinets and furniture with **AI agents that write a parametric design
language**, then compile that language into real, machinable 3D geometry, cut
lists, and hardware schedules.

This follows the pattern proven by [Zoo's **Zookeeper**](https://zoo.dev/research/zookeeper)
agent: the AI does not draw the furniture — it writes *code* in a parametric
language, runs it to build real geometry, checks the result, and repairs its own
code until the design is buildable. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full design, prior-art comparison, and engine rationale.

```
Natural language ─▶ Designer agent (Claude) ─▶ DSL spec ─▶ Validator
                                                   │            │ valid
                         repair ◀─────────────────┤            ▼
                                                   │      Compiler (build123d)
                                                   │            │
                                                   └─ Critic ◀──┘  measure &
                                                      verify        check
                                                        │ pass
                                                        ▼
                          STEP · STL · GLB · cut list · hardware
```

The **Critic** closes the loop: it rebuilds the geometry, measures it, and
checks the overall envelope, part interferences, and front coverage against the
spec — feeding any problem back to the Designer for repair (it caught a real
rail-vs-back collision during development). It runs analytically with no CAD
dependency.

## Why this approach

LLMs are far better at producing and debugging *language* than binary geometry.
So the source of truth is a small, typed **furniture DSL** (see
[`dsl.py`](src/woodworking_ai/dsl.py)) — a JSON spec the agent writes, that is
deterministically validated and compiled. The agent only has to get the *spec*
right; the compiler handles the geometry, and the same spec produces the cut
list and hardware list, so there is a single source of truth.

## Install

```bash
pip install -e .            # core: DSL, validator, cut list (no heavy deps)
pip install -e ".[agent]"   # + the Claude designer agent
pip install -e ".[cad]"     # + build123d for 3D geometry / STEP / STL / GLB
pip install -e ".[all]"     # everything, incl. pytest
```

The DSL, validator, and cut list have **zero CAD dependencies** and run anywhere.
`build123d` (OpenCascade) is only needed to build and export 3D geometry.

## Quickstart

**Build straight from a spec — no API key, no CAD needed:**

```bash
python examples/base_cabinet.py
```

**Natural language → design (needs `ANTHROPIC_API_KEY`):**

```bash
export ANTHROPIC_API_KEY=sk-...
woodai design "36 inch sink base, two shaker doors, soft-close, one shelf"
```

**Also export 3D geometry (needs build123d):**

```bash
woodai design "tall pantry 600 wide, 4 shelves" --out ./out --step --stl
woodai build out/spec.json --out ./out --step   # rebuild from a saved spec
```

Pick the model with `WOODAI_MODEL` (default `claude-opus-4-8`; e.g.
`claude-sonnet-4-6` for cheaper runs).

## The design language (example)

```json
{
  "type": "base_cabinet",
  "name": "Sink Base",
  "width": 900, "height": 720, "depth": 560,
  "material": { "carcass": 18, "back": 6, "door": 18, "shelf": 18 },
  "construction": "frameless",
  "back": "rabbeted",
  "joinery": "dado",
  "toe_kick": { "height": 100, "setback": 50 },
  "shelves": 1, "doors": 2,
  "drawers": [ { "front_height": 140 } ],
  "reveal": 3, "edge_banding": true
}
```

## Project layout

| Path | What |
|---|---|
| `src/woodworking_ai/dsl.py` | The furniture language (typed spec + JSON) |
| `src/woodworking_ai/validator.py` | Type/range + woodworking sanity rules |
| `src/woodworking_ai/cutlist.py` | Spec → parts + hardware (pure math) |
| `src/woodworking_ai/geometry.py` | `panel_layout()` — single source of panel placement |
| `src/woodworking_ai/builder.py` | Spec → build123d B-Rep geometry |
| `src/woodworking_ai/exporters.py` | STEP / STL / GLB / CSV export |
| `src/woodworking_ai/agents/designer.py` | Claude designer + validate/critic-repair loop |
| `src/woodworking_ai/agents/critic.py` | Computational verifier (envelope, interference) |
| `examples/base_cabinet.py` | End-to-end example, no LLM required |
| `tests/` | Pure-math tests (no CAD / API key needed) |

## Run the tests

```bash
pip install -e ".[dev]"
pytest
```

## Status & roadmap

MVP: frameless **base cabinets** end to end, including the **Critic** verify
loop. Next: wall/tall cabinets, face-frame construction, render-based critic
review, sheet nesting + cost, and a web UI with live GLB preview. Full roadmap
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
