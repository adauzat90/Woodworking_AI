# Woodworking AI — Design & Validation Knowledge Base

This directory holds the domain research that underpins the Woodworking AI
**compiler / validator**. The compiler takes a furniture design (parametric
model, parts list, joinery graph) and checks it against a body of rules drawn
from ergonomics, structural engineering, material science, manufacturing
standards, and safety regulations — the same way a programming-language
compiler checks a program against type rules and semantics.

## Documents

| File | Purpose |
|------|---------|
| [`design-principles.md`](./design-principles.md) | How furniture, cabinets, and casework are *properly* designed: standard dimensions, ergonomics, proportion, joinery selection, material behavior. The "why" behind the rules. |
| [`validation-rules.md`](./validation-rules.md) | The concrete catalog of checks the compiler should run, organized by category, each with a severity, a trigger condition, and a rationale. The "what to enforce." |

## Mental model: the design as a compilable artifact

A furniture design can be modeled like a program:

```
SOURCE (parametric model)          COMPILER PHASES
─────────────────────────          ────────────────────────────────────
parts:  panels, rails, legs   →    1. Parse / load geometry
joints: M&T, dado, dowel...   →    2. Resolve references (part A ↔ part B)
material: species, sheet good →    3. "Type check": material + grain rules
loads:  shelf, seat, drawer   →    4. Structural analysis (sag, racking)
intent: table / cabinet / ... →    5. Semantic checks (ergonomics, code)
                              →    6. Emit diagnostics (error/warn/info)
```

Each rule in `validation-rules.md` is one diagnostic the compiler can emit,
with a stable ID (e.g. `DIM-001`, `STRUCT-014`, `MOVE-003`) so it can be
referenced, suppressed, or unit-tested like a lint rule.

## Severity model

- **ERROR** — the piece will likely fail: collapse, joint failure, the
  part can't physically be built, or it violates a mandatory safety standard.
  Blocks "compilation."
- **WARNING** — the piece will probably work but violates best practice or a
  voluntary standard; likely to fail over time (e.g. cross-grain gluing,
  marginal shelf sag).
- **INFO / LINT** — advisory: proportion, ergonomic comfort range, material
  efficiency, finish recommendations.

> Sources for every claim are cited inline in the two documents. Standards
> referenced (ANSI/KCMA A161.1, ASTM F2057, BIFMA, AWI) should be consulted
> directly before treating any numeric threshold as authoritative for
> certification or regulatory purposes.
