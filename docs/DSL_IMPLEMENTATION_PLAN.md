# DSL Agent-Authoring — Implementation Plan

Concrete, sequenced plan to act on every finding in
`docs/DSL_AGENT_AUTHORING_REVIEW.md`. Each work item lists the goal, the exact
files/functions it touches, the approach, back-compat handling, tests, and
effort. Items are ordered so the cheap, high-frequency wins land first and the
structural change (declarative placement) builds on a uniform type model.

Guiding constraints, honored by every item below:
- **Never break stored specs.** `from_dict` must keep accepting today's JSON;
  `convex/schema.ts` stores `spec` as `v.any()`, so additions need no migration.
- **Don't regress the verify-repair loop.** Every new signal must flow through
  `ValidationResult.as_feedback()` (or the parse-error path) so the designer can
  self-repair.
- **Keep the schema hint generated.** Any new vocabulary is emitted from the
  dataclasses via `_opts`, guarded by `tests/test_schema_hint.py`.

A note on one cross-cutting design fact that shapes items 1 and 2: **`from_dict`
discards unknown keys *before* the validator ever runs** (`data = {k: v ... if k
in known}`). So unknown-field and unknown-kind detection cannot live in the
validator — it must happen at parse time, against the *raw* dict. Items 1 and 2
therefore add a thin parse-time lint layer rather than new validator rules.

---

## Phase 0 — Parse-time lint scaffolding (enabler for items 1–2)

**Goal.** A place to collect parse-time diagnostics (unknown kinds, unknown
fields) without changing `from_dict`'s pure, tolerant behavior.

**Approach.** Add `dsl_lint.py` (new module) with:
- `KNOWN_KINDS: frozenset` — the canonical discriminators (`cabinet`, `table`,
  `wall_shelf`, `box`, `bench`, `project`, `assembly`, `appliance_void`), sourced
  from `dispatch.py` so it can't drift.
- `lint_spec_dict(raw: dict) -> list[LintIssue]` — walks the raw payload,
  recursing into `components[].spec`, `definitions{}`, and `accessories[]`,
  routing each node to its target dataclass with the *same* logic as
  `_spec_from_dict`, then diffing the node's keys against that dataclass's
  `__dataclass_fields__`. Uses `difflib.get_close_matches` (stdlib) for "did you
  mean" suggestions.
- `LintIssue(path, key, message)` — `path` is a dotted locator
  (`components[1].spec.hieght`) so feedback points the agent at the exact node.

This module imports from `dsl.py`/`dispatch.py` only; nothing imports it except
the designer path, so the data model stays dependency-free.

**Tests.** `tests/test_dsl_lint.py` — unknown top-level key, nested unknown key
under a component spec, a correct spec yields `[]`, suggestion fires for a near
miss (`hieght`→`height`).

**Effort.** Low. **Risk.** None (additive, off the hot path).

---

## Item 1 — Surface dropped unknown fields as repair warnings *(priority 1)*

Finding #2 in the review — the invisible-typo hole.

**Goal.** When the designer parses a freshly authored spec, any key the model
set that the language dropped is fed back as a warning so the next iteration can
fix it. Storage/round-trip stays silently tolerant.

**Files.**
- `agents/designer.py` — in `design_from_prompt`, after `spec = spec_from_dict(data)`
  succeeds, call `lint_spec_dict(data)`. Merge results into the feedback string
  alongside `result.as_feedback()`. Critically, **a lint warning alone should
  not pass the design as done**: if the spec validates and critiques OK but lint
  found dropped keys, do one more repair round with the lint feedback (cap still
  governed by `max_attempts`). After the cap, return the best spec as today —
  warnings never hard-fail a build.
- `dsl_lint.py` — from Phase 0.

**Feedback wording.** `ignored unknown field 'hieght' at components[1].spec
(did you mean 'height'?)` — actionable, located, non-fatal.

**Back-compat.** `from_dict` is untouched; only the *designer* sees lint. Stored
specs and the public API behave exactly as before.

**Tests.** Extend `tests/test_designer.py` with a stub LLM that emits a typo'd
field on attempt 1 and the corrected field on attempt 2; assert the loop
repairs and the final spec has the value set. Assert a clean spec does **not**
trigger an extra round.

**Effort.** Low. **Risk.** Low — main subtlety is not looping forever on a
lint-only warning; the `max_attempts` cap already bounds it.

---

## Item 2 — Explicit `kind` for every type; reject unknown kinds *(priority 2)*

Findings #1 and #4 — silent misroute to cabinet, and the two-discriminator
inconsistency.

**Goal.** `kind` becomes the single explicit discriminator. A *named but
unrecognized* `kind` produces a clear, recoverable error instead of silently
building a cabinet. Cabinets-without-`kind` (all existing specs, every golden)
still load.

**Files.** `dsl.py::_spec_from_dict` and `spec_from_dict`.

**Approach (precise routing rules).**
1. Read `kind = str(data.get("kind","")).strip().lower()`.
2. Add `"cabinet"` as an explicit accepted kind → `CabinetSpec`.
3. If `kind` is **non-empty and not in `KNOWN_KINDS`**, raise
   `ValueError(f"unknown kind {kind!r}; expected one of {', '.join(sorted(KNOWN_KINDS))}")`.
4. If `kind` is **empty/absent**, keep today's heuristic fallback
   (`"components" in data` → project, `"leg"/"top_thickness" in data` → table,
   else cabinet) so legacy untyped specs are unaffected.

**Why this is safe.** Today's cabinets carry no `kind`, so rule 4 covers them
unchanged. The only new behavior is rule 3, which fires *only* when the model
invented a `kind` — exactly the case we want surfaced. The raised `ValueError`
is already caught in `designer.py`'s parse-error branch and fed back verbatim,
so the helpful "expected one of …" list reaches the agent.

**Hint change.** Advertise `"kind": "cabinet"` as the canonical cabinet
discriminator (with `cabinet_type` as its sub-variant), so the model learns one
mental model. Keep accepting the legacy no-`kind` cabinet shape.

**Back-compat.** Legacy untyped cabinet/table/project specs and all goldens load
unchanged (rule 4). New rejection only triggers on a genuinely unknown named
kind.

**Tests.** `tests/test_types.py` / `tests/test_extensibility.py`: a spec with
`"kind": "wardrobe"` raises `ValueError` whose message lists the valid kinds;
`"kind": "cabinet"` round-trips to `CabinetSpec`; a no-`kind` cabinet still
loads. Confirm `tests/test_designer.py` repairs an unknown-kind response.

**Effort.** Low–Medium. **Risk.** Medium — must verify no golden or example
relies on a stray `kind` that's currently tolerated. Grep goldens/examples for
`"kind"` values before merging.

---

## Item 3 — Declarative / relational placement *(priority 3, structural)*

Finding #3 — multi-piece layout forces coordinate arithmetic onto the model.

**Goal.** Let the author express layout *intent* (a row of pieces along a wall)
and have the loader compute `x`/`y`/`rotation` via the existing `place_run`.
Absolute coordinates remain the escape hatch.

**Files.** `dsl.py` — `ComponentGroup.from_dict`, `Component`, `place_run`
(already present), `DSL_SCHEMA_HINT`; `tests/test_project.py`.

**Approach.** Two complementary, additive shapes:

1. **`runs` container on a group** (primary). In `ComponentGroup.from_dict`, if
   the payload carries `runs`, expand each run through `place_run` and append the
   resulting placed `Component`s to `components`:
   ```jsonc
   { "kind": "project", "name": "Galley",
     "runs": [
       { "start": [0,0], "angle": 0, "gap": 0,
         "items": [ {"spec": {…}}, {"ref": "drawer_bank"}, {"spec": {…}} ] }
     ] }
   ```
   Each item resolves `spec`/`ref` exactly as a component does today, then
   `place_run` steps `x` by cumulative width and sets `rotation = angle`. An L-/
   U-kitchen is two runs at right angles — the model picks a corner gap, never
   does trig.
2. **Relational fallback on a component** (optional, lighter): `"after": "B1"`
   plus `"abut": "right"|"left"|"front"|"back"`. Resolved in a second pass after
   all explicitly-placed components are known. Defer to a follow-up if `runs`
   alone covers the kitchen cases.

**Serialization.** `to_dict` continues to emit fully-resolved `components` (the
canonical, lossless geometry). `runs` is an *input convenience* that expands on
load; a round-tripped project comes back as explicit components. Document this
clearly — it means `runs` is not preserved verbatim across save/load, which is
acceptable because the geometry is identical and the validator/critic operate on
the expanded form.

**Validation.** No new rules needed — expanded components flow through the
existing overlap (SAT) check in `_validate_project`, so a bad `gap` still
reports a collision. Optionally add an info note when `runs` expansion produces
zero-gap abutment (expected) vs. an overlap (already caught).

**Back-compat.** Purely additive; specs without `runs` are unaffected.

**Tests.** `tests/test_project.py`: a `runs` payload expands to the same
components as the equivalent explicit `place_run` call; an L-shaped two-run
project validates without overlap; `ref` inside a run resolves against
`definitions`.

**Effort.** Medium. **Risk.** Medium — the fiddly parts are `ref` resolution
inside runs (reuse `_component_from_dict`) and not double-placing when both
`runs` and `components` are present (define precedence: both allowed, runs append
after explicit components).

---

## Item 4 — Type and validate `accessories`; clarify appliance modeling *(priority 4)*

Findings #5 and #6 — the loose, untyped corner, and appliance modeled two ways.

**Goal.** Bring `accessories` up to the rest of the language: typed, enum-guided,
validated, advertised — *without* disturbing the six modules that consume the
accessory dicts.

**Files.** `dsl.py` (new dataclasses + parse), `validator.py` (accessory
checks), `accessories.py` and consumers (`render`, `cutlist`, `geometry`,
`estimator`, `diffing`) — consumers only if dict shape changes (it won't),
`DSL_SCHEMA_HINT`, tests.

**Approach.**
- Add typed specs: `Countertop`, `Filler`, `EndPanel`, `Molding` (and reuse the
  existing `Appliance`), each with `from_dict`/`to_dict` and enum'd fields:
  `side: left|right`, `molding.type: crown|cove|base|…`, `countertop.material`
  as an enum. Parse `accessories` into these on load.
- **Keep `to_dict` emitting the identical dict shape** the consumers already
  read (`{"kind": "countertop", …}`). This is the key risk-reducer: the typed
  layer is a *parse + validate* improvement; serialization stays byte-compatible,
  so `accessories.py` and the five other consumers need no change and the
  goldens don't move.
- Add accessory validation in `validator.py` (called from `_validate_cabinet`):
  unknown accessory `kind`, bad `side`, missing required dims → structured
  `Issue`s that reach the repair loop.
- **Appliance clarification:** document the split sharply in the hint (hosted
  cutout → `accessories`; floor gap → a component with `kind: appliance_void`).
  *Optional unification* (follow-up): accept a single `appliance` with
  `hosting: "cutout"|"gap"` and route to `Appliance` vs `ApplianceVoid`
  internally. Ship the docs/validation clarity first; the unification is a larger
  change with its own ticket.

**Back-compat.** Loose accessory dicts still parse (typed layer is lenient like
the rest); output shape unchanged → goldens stable.

**Tests.** `tests/test_appliances.py` and a new `tests/test_accessories.py`:
typed round-trip preserves the dict shape; a bad `side` produces an error;
unknown accessory kind is flagged. Confirm goldens unchanged (no `make golden`
needed).

**Effort.** Medium. **Risk.** Low–Medium — guard against changing the emitted
dict shape (that's what would move goldens and break consumers).

---

## Item 5 — Few-shot examples + "pick your kind first" preamble *(priority 5)*

Finding #8 — the prompt is large and cabinet-first.

**Goal.** Raise first-try correctness and cut cabinet bias by leading with a
short type-selection preamble and one *minimal valid example per type*.

**Files.** `dsl.py::DSL_SCHEMA_HINT`, `tests/test_schema_hint.py`.

**Approach.** Prepend a compact decision line ("Choose `kind` first: cabinet |
table | wall_shelf | box | bench | project") and, for each leaf, a 4–8 line
*minimal buildable* example (models copy worked examples more reliably than they
assemble from field tables). Keep the full field reference below the examples.
Keep all enum lists generated via `_opts`.

**Back-compat.** Prompt-only; no code path changes.

**Tests.** Update `tests/test_schema_hint.py` so the guard still asserts every
enum value appears; add an assertion that each `kind` has an example block.

**Effort.** Low. **Risk.** Low.

---

## Item 6 — `schema_version` stamp *(priority 6)*

Finding #7.

**Goal.** A version stamp on output so future breaking changes have something to
branch on; ignored-but-accepted on input.

**Files.** `dsl.py` — add `SCHEMA_VERSION = "1.0"`; emit it in every spec's
`to_dict`; accept and ignore it on input (it's already a non-dataclass key, so
`from_dict`'s unknown-key drop handles input — just add it to the lint
allow-list so Item 1 doesn't warn on it). `convex/schema.ts` needs **no change**
(`spec` is `v.any()`).

**Tests.** `tests/test_dsl_units_enums.py` (or a small new test): `to_dict`
includes `schema_version`; a spec without it still loads; lint does not warn on
it. Note: this adds a key to serialized output → **`make golden` required** to
refresh fixtures (the one item that moves goldens).

**Effort.** Low. **Risk.** Low — the only ripple is regenerating goldens; do it
in this item's commit so the diff is self-contained and reviewable.

---

## Sequencing & dependencies

```
Phase 0 (lint scaffolding)
   ├─> Item 1 (unknown-field warnings)      ← depends on Phase 0
   └─> Item 2 (explicit/rejected kinds)     ← uses KNOWN_KINDS from Phase 0
Item 2 ─> Item 5 (hint preamble leans on the uniform `kind` model)
Item 3 (declarative placement)              ← independent; do after 1–2 land
Item 4 (typed accessories)                  ← independent
Item 6 (schema_version)                     ← independent; sequence LAST so the
                                              golden refresh is isolated
```

Recommended merge order: **Phase 0 → 1 → 2 → 5 → 4 → 3 → 6.** Rationale: 1, 2,
and 5 are small, high-frequency correctness wins with no golden churn; 4 is
medium but golden-neutral; 3 is the structural feature; 6 goes last so the single
golden regeneration sits in its own commit.

## Effort & risk summary

| Item | Change | Effort | Golden churn | Risk |
|---|---|---|---|---|
| 0 | Lint scaffolding | Low | none | none |
| 1 | Unknown-field repair warnings | Low | none | low |
| 2 | Explicit `kind`, reject unknown | Low–Med | none | med (audit goldens) |
| 3 | Declarative placement (`runs`) | Med | none | med |
| 4 | Typed `accessories` | Med | none* | low–med |
| 5 | Few-shot hint + preamble | Low | none | low |
| 6 | `schema_version` stamp | Low | **yes** | low |

\* Item 4 is golden-neutral *only if* the emitted accessory dict shape is kept
byte-identical — the explicit acceptance criterion for that item.

## Definition of done (whole epic)

- `make check` (lint + full pytest) green at every item boundary.
- `tests/test_schema_hint.py` still proves the hint advertises the full
  vocabulary (no drift).
- A regression test for each finding: unknown field repaired, unknown kind
  rejected with a helpful message, a `runs` project expands and validates, a bad
  accessory is flagged, the prompt carries a per-type example, output stamps a
  schema version.
- `docs/DSL_AGENT_AUTHORING_REVIEW.md` updated to mark each finding addressed.
- Goldens regenerated exactly once (Item 6) with a self-contained diff.
