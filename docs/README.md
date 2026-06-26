# Woodworking AI — Documentation

This directory holds the project's living documentation and a domain
knowledge base. The completed/historical planning and audit docs live under
[`archive/`](./archive/) — kept for rationale, but not maintained.

## Living docs

| File | Purpose |
|------|---------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | The system design: agent-writes-language + execute-verify-repair, the pipeline stages, prior art, and the engine rationale. |
| [`ROADMAP.md`](./ROADMAP.md) | What has shipped and what's next. Folds in the old `IMPLEMENTATION_PLAN` / `HOBBYIST_*` / `DSL_*` plans. |
| [`TECH_DEBT.md`](./TECH_DEBT.md) | The current outstanding code-quality debt, graded with `file:line` evidence. Supersedes the three archived audits. |

## Domain knowledge base

The research that underpins the **compiler / validator**: it checks a furniture
design (parametric model, parts list, joinery graph) against rules drawn from
ergonomics, structural engineering, material science, and manufacturing/safety
standards — the way a programming-language compiler checks a program.

| File | Purpose |
|------|---------|
| [`design-principles.md`](./design-principles.md) | How furniture, cabinets, and casework are *properly* designed: standard dimensions, ergonomics, proportion, joinery selection, material behavior. The "why" behind the rules. |
| [`validation-rules.md`](./validation-rules.md) | The concrete catalog of checks the compiler should run, organized by category, each with a severity, a trigger condition, and a rationale. The "what to enforce." |

## Archive

[`archive/`](./archive/) holds completed plans and superseded audits:
`IMPLEMENTATION_PLAN.md`, `HOBBYIST_ROADMAP.md`, `HOBBYIST_PLAN_V2.md`,
`DSL_REVIEW.md`, `DSL_AGENT_AUTHORING_REVIEW.md`, `DSL_IMPLEMENTATION_PLAN.md`,
`TECH_DEBT_AUDIT.md`, `TECH_DEBT_AUDIT_INTEGRATION.md`,
`TECH_DEBT_CLEANUP_PLAN.md`, and `TESTING_CHECKLIST.md`.

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
