# DSL Review — through the lens of the AI agent that *writes* it

A design review of the furniture description language (`src/woodworking_ai/dsl.py`)
evaluated against one specific question: **is this a good language for an LLM to
author?** That is a different question from "is it a good data model." A schema
that a human engineer reads cleanly can still be a minefield for a model that
emits it token-by-token with no compiler in the loop until after the JSON is
done.

This complements the original `DSL_REVIEW.md`, which graded the language as a
data model and is now partly stale (it predates `WallShelfSpec`, `BoxSpec`,
`BenchSpec`, the `Appliance`/`ApplianceVoid` types, and the
`Project`/`Assembly` + `definitions`/`ref` composition layer). Everything below
reflects the language as it stands today.

## How an LLM actually uses this language

1. The whole grammar is handed to the model as one system prompt
   (`DSL_SCHEMA_HINT`, generated from the dataclasses so the advertised
   vocabulary can't drift — a genuinely good decision).
2. The model emits **one JSON object**.
3. `spec_from_dict` routes it to a type; `from_dict` coerces and fills defaults.
4. `validate()` returns structured `Issue`s; the designer loop feeds
   `as_feedback()` back and asks for a corrected object (up to `max_attempts`).
5. On a valid spec, the Critic re-measures the *built* geometry and feeds any
   problem back the same way.

So the language is judged by the model on three axes: **how reliably it can
produce a correct object on the first try**, **how clearly a wrong object is
explained back to it**, and **how cheaply it can express what it means**. The
review is organized around those.

## Verdict at a glance

| Axis | Grade | One line |
|---|---|---|
| First-try correctness | B | Forgiving parsing + buildable defaults help a lot; implicit type routing and silent field-drop hurt. |
| Repairability | A− | Structured per-field issues + a built-geometry Critic are best-in-class for this domain. |
| Expressive economy | B− | Single pieces are terse and natural; multi-piece layout pushes raw coordinate arithmetic onto the worst thing an LLM does. |
| Consistency of the surface | B | Two type-discriminator conventions and a loosely-typed `accessories` corner break the "one language" feel. |

The bones are excellent. The agent-facing weaknesses cluster in three places:
**type routing, the silent-drop of unknown keys, and spatial placement.** Those
are the three things to fix; everything else is polish.

---

## What is genuinely well-designed for an author

- **The schema hint is generated from the enums.** The prompt can never offer a
  value the code rejects, and a guard test asserts every enum value appears.
  This kills the single most common agentic-DSL failure: the model picking a
  vocabulary word the parser has never heard of.
- **Defaults make a minimal spec buildable.** The model can under-specify and
  still get a sound piece; it only has to get right what it actually cares
  about. This is the correct bias for LLM authorship — every required field is a
  chance to be wrong.
- **The repair loop is real, not cosmetic.** `Issue(severity, field, message)`
  gives the model the exact field and the woodworking *why*; the Critic catches
  what static validation can't (cabinet-to-cabinet collisions, envelope drift)
  by measuring built geometry. Few generative-CAD schemas verify the *built*
  artifact and route the failure back into the same language.
- **Tolerant coercion on advisory enums.** An unknown `corner_joint` survives as
  a string for the validator to flag rather than throwing at construction —
  exactly right for a model that occasionally invents a near-synonym.

These should be preserved verbatim through any change below.

---

## Issues, ranked by impact on the agent

### 1. Type routing is implicit, heuristic, and fails *silently* to "cabinet"

`_spec_from_dict` decides what was emitted like this (paraphrased):

```
kind == "appliance_void"            -> ApplianceVoid
kind == "assembly"                  -> Assembly
kind == "project" or "components"   -> Project
kind == "wall_shelf"                -> WallShelfSpec
kind in ("box","chest")             -> BoxSpec
kind in ("bench","stool")           -> BenchSpec
kind == "table" or "leg" in data or "top_thickness" in data -> TableSpec
otherwise                           -> CabinetSpec    # <- silent default
```

Two distinct hazards for an author:

- **The cabinet is the catch-all.** If the model emits `"kind": "wardrobe"`,
  `"kind": "desk"`, or any `kind` not in the list, it is silently built as a
  *cabinet*, and `from_dict` then drops every field the cabinet doesn't
  recognize. The model gets a plausible-looking result for the wrong type and no
  error to repair against. An LLM hallucinating a `kind` is the expected case,
  not the edge case.
- **Structural inference from incidental keys.** Routing to `TableSpec` on
  `"leg" in data` means an unrelated stray key flips the whole build path.
  Inference-by-key-presence is convenient for hand-authored specs but brittle
  for a generator that sometimes emits extra keys.

**Recommendation.** Make `kind` the single explicit discriminator for *every*
type, cabinet included (`"kind": "cabinet"`). Keep the key-presence heuristics
only as a back-compat fallback. Critically, **reject an unknown `kind` with an
error the repair loop can act on** — `unknown kind 'wardrobe'; expected one of
cabinet | table | wall_shelf | box | bench | project | assembly` — instead of
silently defaulting. A wrong-but-named type is recoverable; a silent misroute is
not.

### 2. Unknown *field* names are dropped silently — the author can't tell

`from_dict` ends with "ignore unknown keys so the language can evolve." That is
the right call for *stored* specs (forward compatibility). It is the wrong call
for a *freshly authored* spec, because it also swallows typos:

- `"hieght": 720` → dropped; the default 720 happens to mask it.
- `"door_count": 2` (model guessed the field name) → dropped; `doors` stays at
  its default.

The model believes it set a value it did not set, validation passes, and the
piece is subtly wrong with **no feedback anywhere in the loop**. This is the
most insidious agent-facing bug class because it is invisible.

**Recommendation.** Split the two concerns. Keep silent tolerance for the
storage/round-trip path, but in the **designer path** collect the dropped keys
and surface them as *warnings* in the validation feedback: `ignored unknown
field 'hieght' (did you mean 'height'?)`. Don't make them errors — that would
break forward-compat — but do put them in front of the author. A cheap
Levenshtein "did you mean" against the dataclass fields turns a silent failure
into a one-iteration repair. This is the highest value-per-line fix in the
review.

### 3. Multi-piece layout makes the model do the one thing it's worst at

Composition is absolute-coordinate: every `Component` carries `x`, `y`,
`rotation`, and the model must place pieces so footprints abut but don't overlap
— stepping `x` by the cumulative width of everything to its left, and doing
trig for an L-/U-shaped run around a corner. Arithmetic layout over many items
is precisely the failure mode of token-by-token generation. The validator's
overlap check (oriented-footprint SAT — nice) catches the collision *after the
fact*, but then hands the model back a geometry error and asks it to re-derive
the coordinates it already got wrong.

Tellingly, the codebase already knows the right abstraction: `place_run()` lays
specs along a wall by stepping `x` automatically. But it's a **Python helper the
LLM can't call** — the model still has to emit the raw numbers `place_run`
would have computed.

**Recommendation.** Lift `place_run` into the *language*. Give the author a
declarative way to express layout *intent* and let the loader compute
coordinates:

```jsonc
{ "kind": "project", "name": "Galley",
  "runs": [
    { "along": "wall_a", "angle": 0,  "start": [0, 0],
      "gap": 0, "components": [ {spec…}, {spec…}, {spec…} ] }
  ] }
```

or, lighter, a relational placement on each component (`"after": "B1"`,
`"abut": "right"`). The model expresses "these sit in a row on this wall, in
this order" — which it does reliably — and never touches cumulative arithmetic.
Absolute `x`/`y` stays as the escape hatch. This is the single biggest
agent-ergonomics win available and it reuses code that already exists.

### 4. The surface carries two type-discriminator conventions

A cabinet has **no `kind`** and is selected by `cabinet_type`; every other leaf
uses `kind`. So the model must hold two mental models: "for a cabinet, set
`cabinet_type`; for everything else, set `kind`." It weakens the "one language"
story and feeds directly into issue #1 (the cabinet being the unnamed default).

**Recommendation.** Standardize on `kind` everywhere and make `cabinet_type` a
sub-variant *under* `"kind": "cabinet"`. Accept the old shape for back-compat
but advertise only the uniform one in the hint.

### 5. `accessories` is the loosely-typed corner of an otherwise typed language

Everything else is a typed dataclass with enum-guided fields. `accessories` is a
list of free-form dicts (`countertop`, `filler`, `end_panel`, `molding`, and the
`appliance` cutout). The model gets no enum guidance for them, and a wrong field
name or a bad `material: "butcher_block"` value is dropped/ignored with the same
silence as issue #2. This is both the least-evolved and the most error-prone
part of the language for an author.

**Recommendation.** Promote the accessory kinds to typed specs with their own
schema-hint fragments and validation (allowed `kind`s, enum'd materials/sides).
Even just enumerating the legal `kind`s and their fields in the hint, plus
validating them, would close most of the gap.

### 6. "Appliance" is modeled two different ways

There are two representations: an `Appliance` that lives **inside
`accessories`** (`kind: "appliance"`, a hosted cutout — sink/cooktop) and an
`ApplianceVoid` that is a **standalone component** (`kind: "appliance_void"`, a
floor gap — dishwasher/range/fridge). The distinction (a cutout hosted by a
countertop vs. a reserved gap in a run) is real and correct, but the author has
to learn that "appliance" means two different shapes placed in two different
containers depending on the appliance. That's a memorization tax with a real
error rate.

**Recommendation.** At minimum, state the split sharply and early in the hint
("hosted cutout → `accessories`; floor gap → component"). Better: unify under a
single `appliance` with a `hosting: "cutout" | "gap"` field and let the loader
place it correctly, so the author makes one decision instead of two.

### 7. No `schema_version`, though specs are persisted

Specs are stored (`convex/`). Unknown-key tolerance gives forward-compat, but
there is no version stamp, so a future breaking change has nothing to branch on
and the validator can't tailor a message to the spec's vintage. Low urgency,
cheap to add now, expensive to retrofit later.

**Recommendation.** Stamp `schema_version` on output; default it on input.

### 8. The prompt is large and cabinet-first

`DSL_SCHEMA_HINT` is ~220 lines with the richest type (cabinet) first. Two
known LLM effects: the lead type biases output toward cabinets, and field-tables
are followed less reliably than examples are copied.

**Recommendation.** Add a short "pick your `kind` first" preamble and one
*minimal valid example per type* (few-shot). Models copy a worked example far
more reliably than they assemble one from a field reference. The full reference
can stay below the examples.

---

## Prioritized plan

| # | Change | Why it matters to the agent | Effort |
|---|---|---|---|
| 1 | Surface dropped unknown fields as repair warnings (designer path) | Closes the invisible-typo hole; turns silent wrong-spec into a 1-iteration fix | Low |
| 2 | Explicit `kind` for all types; reject unknown `kind` | Kills silent misroute-to-cabinet; gives a recoverable error | Low–Med |
| 3 | Declarative/relational placement (`runs`/`abut`), reusing `place_run` | Removes the hardest numeric task from the model | Med |
| 4 | Type & validate `accessories`; unify appliance modeling | Extends enum guidance + repair to the last loose corner | Med |
| 5 | Few-shot minimal example per type; "pick kind first" preamble | Higher first-try correctness, less cabinet bias | Low |
| 6 | `schema_version` stamp | Cheap now, enables future migrations | Low |

Items 1, 2, and 5 are small and remove the highest-frequency silent failures;
item 3 is the structural win for real kitchens/built-ins.

## Bottom line

As a *data model* this language is already strong, and the original review
captured that. As a *language an LLM authors*, its three real liabilities are
that wrong types and wrong field names fail **silently** (so the repair loop
never sees them), and that multi-piece layout demands exactly the arithmetic
LLMs are least reliable at. The fixes are mostly additive and the hardest one
(#3) reuses code that already exists. The verify-and-repair architecture around
the language is the asset to protect — every recommendation above is about
getting more of the model's mistakes *into* that loop instead of letting them
pass through unseen.
