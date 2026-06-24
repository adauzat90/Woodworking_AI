# DSL Review — the furniture description language for AI agents

A review of the spec language the AI agents write (`src/woodworking_ai/dsl.py`)
and the pipeline around it — assessing how **complete**, **powerful**, and
**understandable** it is.

## What it is

The "DSL" is a small, typed, declarative spec emitted by the agents as a single
JSON object. Two spec types exist — `CabinetSpec` (rich) and `TableSpec` (lean)
— implemented as Python dataclasses with JSON (de)serialization and zero CAD
dependency. A valid spec is the single source of truth from which geometry, a
cut list, and a hardware schedule are derived. The design philosophy
(agent-writes-language + execute-verify-repair, after Zoo's Zookeeper and
Seek-CAD) is sound and documented in `docs/ARCHITECTURE.md`.

## Verdict at a glance

| Dimension | Grade | Summary |
|---|---|---|
| Understandability | A | Exceptionally clear and well-commented; reads like a domain expert wrote it. |
| Power (single cabinet) | A− | Real engineering, hardware, joinery, and corner geometry — genuinely deep. |
| Completeness (as a language) | B− | Strong within scope, but the scope is narrow: one piece at a time, agent path is cabinet-only. |
| Soundness / consistency | B | A few real gaps: `units` is decorative; the schema hint diverges from the type. |

## Strengths

1. **The "design as code" discipline is real.** Validation runs *before*
   geometry (`validator.py`); a deterministic Critic re-measures the *built*
   geometry against the spec (`agents/critic.py`) and feeds structured repair
   notes back to the LLM (`agents/designer.py`). Panel placement lives in one
   place (`geometry.py::panel_layout`), consumed by both the compiler and the
   Critic, so the verified model can't drift from the built model.

2. **The embedded domain knowledge is the standout feature.** The validator
   enforces first-principles shelf sag (`engineering.py`: δ = 5wL⁴/384EI) with
   per-species modulus against both a structural (span/360) and a *visible*
   deflection limit; ASTM F2057 tip-over scope; KCMA A161.1 toe-kick minimums;
   35 mm Euro hinge cup geometry; 32 mm-system drilling feasibility; side-mount
   slide clearances; and solid-wood seasonal movement. A *spec language* that
   carries citable standards (ASTM, KCMA, ANSI) is rare and powerful.

3. **Understandability is excellent.** Every field has an inline comment
   explaining the woodworking *why*. Defaults encode good practice, so a minimal
   spec is still buildable. `from_dict` ignores unknown keys, letting the
   language evolve without breaking stored specs.

## Gaps & issues (most material first)

1. **`units` is decorative on *input* — a latent correctness bug.** The field
   exists on both specs and in the schema hint, but nothing converts on it for
   *input*: every module assumes mm. An agent emitting `"units": "in"` with inch
   values is silently treated as mm. The only safeguard is an LLM prompt
   instruction. Make the field load-bearing on input (normalize to mm in
   `from_dict`) or remove it.

   > **Update — imperial *output* now implemented.** Since most users are US
   > shops working in fractional inches, an imperial **display layer**
   > (`units.py`) was added: the engine stays millimetre-native, but the cut
   > list, cost/critic reports, CSV downloads, and the web UI can render in
   > fractional inches (to 1/16″) via a units toggle (`--imperial` on the CLI,
   > a `units` field on `/api/export`, a dropdown in the SPA). *Input* hardening
   > followed (see recommendation 1 below): `from_dict` now converts an
   > imperial-valued spec to mm on load, so the field is fully load-bearing.

2. **The agent can only ever produce a cabinet.** `designer.py` hard-codes
   `CabinetSpec.from_dict`, and `DSL_SCHEMA_HINT` describes cabinets only. The
   polymorphic `spec_from_dict` and the full `TableSpec` pipeline exist but the
   NL→DSL path can never reach them — a table request yields a cabinet. Include
   both schemas in the prompt and route via `spec_from_dict`.

3. **The schema hint advertises a smaller language than exists.** `Joinery` has
   10 members but the hint shows only 4 (`dado | dowel | domino | screw`), so
   the agent never chooses `pocket`/`rabbet`/`mortise_tenon`/etc. Generate the
   hint from the dataclasses (or add a test asserting every enum value appears).

4. **The language describes one component, not an assembly.** No run of
   cabinets, no project container, no fixed relationships between pieces. This is
   the biggest completeness ceiling for real kitchens/built-ins.

5. **`TableSpec` is a second-class citizen.** Less engineering rigor than
   `CabinetSpec`, free-string fields where the cabinet uses typed enums, not in
   the schema hint, and `kind` vs `cabinet_type` stylistic divergence weakens the
   "one language" story.

6. **Minor type-safety asymmetry.** `Drawer.corner_joint`/`slide_type` are
   stringly-typed while the cabinet's joinery is an enum. Promote to enums for
   parity and self-documentation.

## Recommendations (prioritized) — all implemented ✅

1. **Make `units` sound — done.** `from_dict` now converts an imperial-valued
   spec (`"units": "in"`) to canonical mm on load (lengths only; counts/loads
   untouched) and stamps `units = "mm"`. The web form's units toggle now drives
   *input* too (inches in, converted on submit; mm specs shown back in inches).
   Tests: `tests/test_dsl_units_enums.py`.
2. **Wire the table type into the designer — done.** `designer.py` routes via
   `spec_from_dict`, the prompt carries both the cabinet and table schemas, and
   `DesignResult.spec` is `CabinetSpec | TableSpec`. Tests: `tests/test_designer.py`.
3. **Generate `DSL_SCHEMA_HINT` from the dataclasses — done.** The enum option
   lists in the hint are built from the enums (`_opts`), so they can't drift; a
   guard test asserts every enum value appears. Tests: `tests/test_schema_hint.py`.
4. **Promote `Drawer`/`TableSpec` string fields to enums — done.** New
   `StrEnum`s `CornerJoint`, `DovetailTails`, `SlideType`, `Grain`, `TopFixing`
   (and `TableSpec.joinery` now reuses `Joinery`), coerced in `__post_init__`
   (tolerant: unknown values stay strings for the validator to flag).
5. **Assembly/project layer — done.** `Component` + `Project` hold placed specs;
   `validate`, `generate_cutlist`, and `estimate` accept a `Project` and
   aggregate across components (combined cut list tagged per cabinet, summed
   quote, placement-overlap check). It also assembles into **one 3D model**:
   `geometry.project_layout` places every component's panels in the run frame,
   so the Critic detects cabinet-to-cabinet collisions and `builder.build_project`
   exports the whole run as a single GLB/STEP (and `--dxf` nests every part into
   one cut-layout). Tests: `tests/test_project.py`.

A note on enum strictness: the *structural* enums (`cabinet_type`,
`construction`, `back`, `joinery` on a cabinet) stay strict — an unknown value
raises, because it selects the whole build path. The advisory drawer/table
sub-fields degrade gracefully to a validator warning instead.

## Bottom line

A genuinely well-conceived DSL: the verify-repair loop is correctly built, and
the embedded engineering/standards knowledge gives it authority most
generative-CAD schemas lack. Its weaknesses are scope (single-component,
cabinet-biased agent path) and a handful of consistency gaps where the
*advertised* language has drifted from the *implemented* one (`units`, the
joinery vocabulary, the unreachable table path). Fixing items 1–3 closes almost
all the soundness gaps with modest effort.
