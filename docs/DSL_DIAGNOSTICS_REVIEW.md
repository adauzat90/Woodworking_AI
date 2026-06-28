# DSL Diagnostics Review — info / warning / error

> An architect's review of the diagnostics the Woodworking_AI DSL emits — the
> `error:` / `warning:` / `info:` lines from `validator.py`, `dsl_lint.py`, and
> the `engineering.py` calculators behind them. Scope: the **quality and
> coverage of the messages themselves** and the structure that carries them,
> not the geometry/CAD pipeline.
>
> Companion docs: [`validation-rules.md`](./validation-rules.md) (the rule
> catalog) and [`design-principles.md`](./design-principles.md) (the why).
> Pairs with the tech-debt findings in [`TECH_DEBT.md`](./TECH_DEBT.md).

---

## TL;DR

The diagnostics layer is genuinely good: dependency-light, dataclass-based,
with strong **fix-hint discipline** on the high-value structural/hardware/
movement rules, and correct severity gating (`info` never blocks the repair
loop). It is one of the best parts of the codebase.

Three structural weaknesses limit it, and there is real room to add checks:

1. **Rule IDs live only in comments and docs — never on the emitted `Issue`.**
   The catalog is built around stable IDs (`STRUCT-020`, `HW-001`) and promises
   `// noqa: STRUCT-014` suppression, but nothing in the runtime carries an ID.
   Suppression and audit-by-ID are unimplemented.
2. **The catalog claims "every rule is now implemented." It isn't** — ~20+
   catalogued rules have no emitter (most DIM ergonomics, the STD meta-rules,
   several MOVE/GRAIN/STRUCT enclosure rules). The omissions are silent, not
   flagged.
3. **Diagnostics are prose-only.** The offending value, the limit, and the fix
   are jammed into one English string. The LLM repair loop has to parse prose to
   know what number to change. There is no structured `(observed, limit, units,
   fix)` for a machine to act on.

Plus a high-severity correctness smell: **the shelf-sag safety check silently
falls back to plywood stiffness when a species name doesn't resolve** — a real
white-oak shelf can be validated as plywood with no warning (§4.1).

The rest of this doc: how diagnostics are structured (§1), concrete fixes to the
**existing** messages (§2–3), **new** checks worth adding (§4), the DSL
expressiveness gaps that block better diagnostics (§5), and a prioritized plan
(§6).

---

## 1. How diagnostics are structured today

Three independent representations, no shared base:

| Layer | Type | Fields | Severity |
|---|---|---|---|
| Validator | `Issue` (`validator.py:72`) | `severity, field, message` | bare **string** `"error"\|"warning"\|"info"` |
| Parse lint | `LintIssue` (`dsl_lint.py:71`) | `path, key, message` | **none** — consumer decides |
| Engineering | `ShelfResult.status` (`engineering.py`) | `"fail"\|"visible"\|"ok"` | string status mapped by caller |

`ValidationResult` (`validator.py:82`) wraps `list[Issue]` and derives `.ok`,
`.errors`, `.warnings`, `.infos`, `as_feedback()`. Leaf validators are
dispatched through the `furniture` registry and each returns a flat `list[Issue]`
built by local `err/warn/info` closures (repeated at ~10 sites).

**Observations:**
- Severity is **stringly-typed**. A typo (`"warn"` vs `"warning"`) misclassifies
  silently because `.ok`/`.warnings` filter on exact strings (`validator.py:88,96`).
  Make it a `Severity(StrEnum)`.
- `Issue` and `LintIssue` have **divergent shapes and no common protocol**;
  every consumer special-cases them. Unify under one `Diagnostic`.
- Rule IDs are **not a field** — only code comments (`# HW-001/002`) and the
  catalog carry them.

---

## 2. Make diagnostics machine-actionable (highest-leverage change)

The repair loop is an LLM reading `as_feedback()` prose. Today a sag error reads:

```
[error] shelves: shelf will sag 3.4mm over a 900mm span, past the 2.5mm
structural limit (span/360); shorten span, thicken, stiffen, or add support
```

Everything the agent needs is in there — but only as English. Promote it to a
single structured record:

```python
class Severity(StrEnum):
    ERROR = "error"; WARNING = "warning"; INFO = "info"

@dataclass
class Diagnostic:
    rule_id: str          # "STRUCT-020"  — stable, suppressible, testable
    severity: Severity
    field: str            # "shelves" / "material.door" / dotted path
    message: str          # human prose (unchanged)
    fix: str | None       # the remedy, separated from the observation
    observed: float | None = None   # 3.4
    limit: float | None = None      # 2.5
    units: str | None = None        # "mm"
    doc_anchor: str | None = None   # "design-principles.md#33-shelf-sag"
```

Wins, in order of value:
- **`rule_id` on every diagnostic** unlocks the suppression the catalog already
  promises (`// noqa: STRUCT-014`), per-rule unit tests keyed by ID, and lets the
  agent/UX link to the explanation. This is the single most impactful change and
  it's mechanical — the IDs already exist in comments next to each emitter.
- **`observed` / `limit` / `units`** let the repair loop compute the exact edit
  ("thicken shelf until `limit ≥ observed`") instead of regex-parsing prose, and
  let the UI render a gauge / "92% of limit" without string surgery.
- **`fix` split from `message`** stops the two drifting and lets the UI show the
  remedy as an action button.
- **`doc_anchor`** turns every diagnostic into a teaching moment (the principles
  doc already has the sections).

Keep `__str__`/`as_feedback()` rendering identical so existing prose-based tests
and CLI output don't move. This is additive.

---

## 3. Fixes to the *existing* messages

### 3.1 Move the ~15 inline thresholds into the config table
The catalog's own directive (`validation-rules.md:208`: *"Numeric thresholds
belong in a data table, not code"*) is only half-honored. Named constants exist,
but these are still inline literals in conditions **and baked into message
prose**, where they can drift from the condition:

| Literal | Where | Note |
|---|---|---|
| `350` / `1200` table height | `validator.py:142` | "typical 700–760mm" is a *third* copy of the range, in prose |
| `6.0` mm movement | `:157` | seasonal-allowance warn threshold |
| `0.06` / `0.08` leg ratio | `:191,195` | spindly/heavy leg |
| `10.0` / `14.0` slide band | `:435` | side-mount clearance tolerance |
| `16.0` door stock | `:480,484` | hinge backing; literal also in message |
| `600` single-door sag | `:568` | |
| `450` wall depth, `1500` tall, `700` base depth | `:581,587,619` | |
| `300` / `200` shelf bay | `:610,613` | hardback/paperback, literals in message |
| `0.40` tip factor | `:652` | |
| `2440×1220` sheet | `:686` | **no unit suffix** in the message string |

Lift each into a named constant (or the versioned threshold table the catalog
envisions), and **interpolate the constant into the message** so the prose can't
drift from the check.

### 3.2 Give the bare bound-checks a remedy
High-value rules carry fix hints; the type/bound checks are bare observations —
*"carcass box height collapses after removing toe kick"* (`:551`), *"drawers are
unusual in a wall cabinet"* (`:580`). Either add a one-clause remedy ("raise
`height` or reduce `toe_kick.height`") or, for the genuinely-just-FYI ones, drop
them to `info`. The catalog claims *"every diagnostic carries a fix hint"*
(`:222`); make that true or soften the claim.

### 3.3 Fix the small concrete defects
- **Dead check:** `shelves < 0` (`validator.py:557`) is unreachable — line 530
  already errors if `shelves` isn't an int in `0..MAX_SHELVES`. Delete it.
- **ID mislabel:** the comment at `validator.py:457` tags the slide-depth-waste
  check `HW-003`, but catalog `HW-003` is "inset drawer depth not reduced." The
  in-code labels aren't a reliable index — another reason to make `rule_id` a
  real, tested field (§2).
- **Missing unit:** the `2440×1220` sheet size (`:686`) has no `mm`.
- **Implicit string concatenation** across adjacent literals (e.g. `:477–479`)
  is where a dropped leading/trailing space hides. Once messages are templated
  from a constant + value (§3.1), collapse these to single f-strings.

### 3.4 House style for messages
Pick one. Today messages mix lead-with-subject / lead-with-verb / bare
fragments, and `field` is sometimes a dotted path (`material.door`,
`toe_kick.height`), sometimes bare (`drawers`). Convention: **`field` is always a
spec path** (so the UI can deep-link / the agent can target the edit), and
**`message` states the observation, `fix` states the imperative remedy.**

---

## 4. New diagnostics worth adding

Grouped by value. The first two are the ones I'd ship first.

### 4.1 ⚠️ Species → stiffness silent fallback (correctness — do first)
`engineering.modulus_for` resolves a species *name* to Young's modulus, then
**silently returns the plywood default (10300 MPa) for any unrecognized name**
(`engineering.py:50–64`). The shelf-sag *safety* check (`STRUCT-020`, an ERROR)
runs on that E. So a `shelf_species: "white_oak"` typo, or any species not in the
~11-entry table, gets a real oak shelf evaluated as plywood — and oak is ~1.8×
stiffer, so the check can pass a shelf that will actually sag, or vice-versa,
**with no diagnostic at all.** Worse: a cabinet authored with `species: "oak"` but
no `shelf_species` is checked against the plywood default, because the make-up
field and the stiffness field don't talk to each other (§5).

Add:
- `MAT-006` **WARN**: *"shelf stiffness species 'white_oak' isn't in the modulus
  database; sag computed using plywood (10300 MPa). Pick a known species or set
  an explicit `shelf_modulus`."* Emit whenever `modulus_for` falls back.
- `MAT-007` **INFO**: *"`shelf_species` unset; using piece species 'oak' for sag
  (E≈12400 MPa)."* — make the two fields cooperate instead of silently diverging.

This is the highest-value addition: it converts a silent safety-relevant failure
into a visible one, and it's a few lines.

### 4.2 Assembled weight / liftability & hanging load
The species DB already carries density, so weight is free to compute.
- `STRUCT-043` **WARN** (catalogued, not emitted): a wall cabinet's self-weight +
  rated contents vs. its hanging method / back thickness (KCMA tests to 600 lb).
- `HW-007` **INFO/WARN** (new): a single part or sub-assembly exceeding ~25 kg
  (one-person lift) — flag for knock-down joinery or a second person. Genuinely
  useful for big tops, workbench slabs, tall pantry carcasses.
- `HW-008` **WARN** (new): door area/weight beyond a 2-hinge rating → *"add a
  third hinge."* Pure hardware geometry, like the existing HW-005.

### 4.3 Catalogued-but-unimplemented rules (close the gap)
These are in `validation-rules.md` with no emitter. Priority order:
- **DIM-004** (**ERROR**) seat↔top thigh-clearance coupling — the catalog's only
  *coupled-dimension error* and it has no check. Needs the assembly-level pass
  the catalog already calls for. High value for tables+seating sets.
- **DIM-001/002/003/005/006** ergonomic heights (dining/counter/bar/desk/seat).
  Today only a vague "unusual table height" (`validator.py:142`) exists.
- **STRUCT-001/003/004** base racking — stretchers / corner-block advisories
  (only STRUCT-002 leg-to-apron joint is emitted).
- **STRUCT-014** shelf-into-case-side butt/screw (dado/rabbet remedy).
- **STRUCT-040/041** KCMA full-enclosure (missing back/bottom/sides/top).
- **MOVE-003/004/005** frame-and-panel float gap, breadboard slotting,
  cross-grain glue — the "silent failure" checks the principles doc calls the
  highest-value. Currently only the tabletop-fixing MOVE-001/002 fire.
- **GRAIN-002/003/004** grain orientation, wide-board glue-up, mixed sawn.
- **STD-001..004** meta "did you run the KCMA/ASTM/BIFMA/AWI set" reminders —
  cheap, and they make the standards coverage legible.

Update the catalog's `:194` "every rule is implemented" line either way — today
it contradicts its own status table.

### 4.4 Positive confirmations & near-miss advisories
The loop is all-negative, which pushes the agent to over-repair. Add:
- **INFO confirmations** with margin: *"passes ASTM F2057 tip-over with 35%
  margin"*, *"shelf sag 1.1mm of a 2.5mm limit (44%)."* Gives the agent a reason
  to *stop* editing.
- **Near-miss WARN** at e.g. ≥90% of a hard limit: *"shelf at 94% of the
  deflection limit — a small load increase will fail it."* Cheap once §2 gives
  diagnostics `observed`/`limit`.

### 4.5 Other genuinely new checks
- **Drawer-bottom sag** for wide drawers — same beam model as shelves, different
  part. Already have the calculator.
- **Joinery proportion** — tenon ≈ ⅓ stock thickness, min mortise wall; flag
  out-of-proportion M&T once joints carry sizes.
- **Screw/fastener into end grain** (GRAIN) — pocket screws or case screws
  driven into end grain hold poorly; pairs with the existing joinery data.
- **Finish/material compatibility** advisories (a `finishing.py` already exists)
  — e.g. oily exotics + PVA glue, water-based finish on raised end grain.

---

## 5. DSL expressiveness gaps that *block* better diagnostics

Several rules can't be sharpened because the DSL can't express their inputs.
These are the real ceiling on diagnostic quality:

1. **Load is a single uniform scalar** (`shelf_load_kg_per_m`). No point load, no
   cantilever/overhang, no fixed-end support for a shelf. The bed sleeping load
   isn't authorable at all — it's a literal `180.0` in `furniture_types.py:1114`.
   → add a small load model (`load: {type: uniform|point, kg, kg_per_m,
   support: simple|fixed|center}`).
2. **Species → E is a lossy string lookup with a silent default** (§4.1). → allow
   an explicit `shelf_modulus` / `modulus` override, and make the fallback warn.
3. **`species` (make-up) and `shelf_species` (stiffness) are two fields that
   don't cooperate** → default `shelf_species` from `species`, warn when they
   conflict.
4. **Joints are per-spec enums, not part-to-part relations.** The validator can
   say "the carcass joinery is butt" but can't reason about *which* edge, or
   shelf-to-side attachment, so STRUCT-014 / MOVE-003 have nothing to check
   against. → a minimal `joints: [{between: [a,b], type, edge}]` would unlock a
   whole class of MOVE/GRAIN/STRUCT rules. *(Partially closed: a targeted
   `CabinetSpec.shelf_joint` field now unblocks STRUCT-014, and MOVE-003 turned
   out checkable from the existing `door_style` + make-up without a relation
   model — see §6. The general `joints` relation is still what MOVE-005 needs.)*
5. **Grain is binary (`flatsawn|quartersawn`) and top-only.** No riftsawn, no
   per-part orientation; cabinets/boxes have no grain field even though the
   back-groove short-grain rule reasons about grain. → per-part grain for solid
   parts.
6. **Auto-derived counts** (`slat_count`, `dog_hole_count`, …) default to 0 =
   "auto"; the validator reasons over a number the author can't see. → echo the
   resolved value in the relevant diagnostic.

Each gap is also a chance to **warn when the author leaves a safety-relevant
field defaulted** (no load specified on a long shelf, no grain on a wide solid
panel) rather than silently picking a default and validating against it.

---

## 6. Suggested order of attack

**Tier 1 — correctness & leverage (small, high value): ✅ DONE**
1. ✅ **Species-fallback warning** (`MAT-006/007`, §4.1) — `engineering.
   resolve_modulus` now reports whether a name resolved; the cabinet sag check
   warns (`MAT-006`) when it falls back to plywood and INFOs (`MAT-007`) when a
   solid-wood piece left `shelf_species` at the plywood default. Converts a
   silent safety-relevant failure into a visible one.
2. ✅ **`rule_id` + `Severity` enum on `Issue`** (§2) — `Issue.rule_id` is
   populated for the structural/hardware/movement/material/proportion/dimensional
   rules; `Severity` is a `StrEnum` (compares equal to the legacy strings);
   `ValidationResult.by_rule(id)` queries by stable ID. Rendered output is
   unchanged (ID is programmatic only), so no prose tests moved.
3. ✅ **Deleted the dead `shelves < 0` check; fixed the `HW-003` mislabel** (now
   `HW-006`) **& the missing `2440×1220mm` sheet unit** (§3.3).

Covered by `tests/test_dsl_diagnostics.py`. The remaining structured-diagnostic
work (`observed`/`limit`/`units`, splitting `fix` from `message`, unifying
`Issue`/`LintIssue`) is Tier 2.

**Tier 2 — structure: ✅ DONE**
4. ✅ **Added `observed`/`limit`/`units` + a `fix` field** (§2) — `Issue` now
   carries a machine-actionable record alongside the prose, populated on the
   numeric rules (STRUCT-020/021, STRUCT-031, MOVE-001/002, HW-001/002/005,
   DIM-007/008/010, MAT-002, single-door width). `fix` is the imperative remedy
   split out of the message (the prose still embeds it, so rendering is
   unchanged); `doc_anchor` deep-links each into `design-principles.md`. The web
   `build_result` bundle serialises every populated field and omits the empty
   ones. The repair loop can now compute the exact edit instead of regex-parsing
   English.
5. ✅ **Unified `Issue`/`LintIssue` under a shared `Diagnostic` protocol** — a new
   `diagnostics.py` holds `Severity` (moved out of `validator`, still re-exported)
   and a structural `Diagnostic` protocol (`severity`/`field`/`message`/
   `rule_id`). `LintIssue` now reports `severity="warning"`, `field` (aliasing its
   dotted `path`), and `rule_id="LINT-001"`; both records `isinstance`-pass the
   protocol, so consumers fold lint + validation into one stream. `LintIssue`
   rendering (`__str__`, `.path`/`.key`) is unchanged.
6. ✅ **Lifted the inline thresholds into named constants and interpolated them
   into the messages** (§3.1) — table-height bounds, seasonal-movement warn,
   leg-ratio factors, slide-clearance band, door stock, single-door width, the
   per-type cabinet depths/height, bookcase bay clearances, tip factor, and the
   sheet size are all named constants now, and the prose reads the constant so it
   can't drift from the condition.

Covered by the Tier-2 additions in `tests/test_dsl_diagnostics.py` (structured
fields on the sag/tip rules, the `Diagnostic` protocol membership, and the
`build_result` serialisation).

**Tier 2 — post-landing evaluation pass (addressed):** a second review of the
Tier-2 change surfaced four fair critiques, now fixed:
- **`(observed, limit)` wasn't self-describing.** STRUCT-031 tip-over is
  *smaller-is-worse* while every other rule is *bigger-is-worse*, so a rule-
  agnostic repair loop couldn't tell which way to edit. Added a `direction`
  field (`"max"`/`"min"`/`"target"`/`""`) on every structured rule; an empty
  `direction` also documents the `limit`-is-a-trigger (not a target) case
  (MOVE-002), closing the `limit=None` ambiguity.
- **STRUCT-031 carried no number in its prose and no `units`.** It now reads
  `depth/height 0.28 < 0.40` and sets `units="ratio"`.
- **Coverage gap:** STRUCT-042 (toe-kick minimums) was a clean numeric check
  with no structured fields — now carries `observed/limit/units/direction/fix`.
- **The `Diagnostic` protocol was over-sold.** It's a *latent* common shape:
  both records conform and it's tested, but no consumer routes through it yet
  (the designer loop / CLI / web service still handle lint and validation
  separately). The docstrings now say so honestly, and note that
  `@runtime_checkable isinstance` is presence-only, not type validation. Wiring
  one consumer through the protocol is a Tier-3 follow-up.

A `doc_anchor` drift-guard test now parses `design-principles.md` headings and
asserts every emitted anchor resolves, so a heading rename can't silently break
the deep links.

**Tier 3 — coverage:**

*The unblocked cluster (no schema change needed) is ✅ DONE:*

7. ✅ **DIM-004 seat↔top coupling + the unblocked ergonomic heights** (§4.3) —
   `DIM-004` (WARN) runs on the project pass, pairing each seat to its **best-fit**
   table and flagging only a genuinely uncomfortable thigh gap (best-fit avoids
   cross-flagging a counter's stools against a dining table). `DIM-005` (desk
   height/depth), `DIM-003` (bench/stool seat height) and `DIM-006` (knee
   clearance under an apron) are wired too. **`DIM-001`/`DIM-002`
   (dining/counter/bar table heights) are deliberately deferred** — with no table
   sub-type a coffee table can't be told from an under-height dining table, so an
   absolute-height check would false-positive; it needs a `table` sub-type field
   (a §5 gap) first. `DIM-004` is softened from the catalog's ERROR to WARN
   because, with no explicit seat↔table link in the DSL, the pairing is inferred.
8. ✅ **Weight/liftability + hanging load** (§4.2) — new `mass.py` estimates part
   and assembly weight from the cut list × density (solid-wood density from the
   species DB; a sheet-goods table for plywood/MDF/…). `HW-007` (WARN) flags a
   single part past the ~25 kg one-person lift; `STRUCT-043` (INFO) notes a wall
   cabinet's self-weight hangs on its fixing. (`HW-008` door-weight→3rd-hinge is
   deferred — it needs reliable per-door density resolution.)
10. ✅ **Near-miss advisories** (§4.4) — a passing structural check within 10% of
    its limit now emits a pass-side INFO (shelf sag approaching the visible limit;
    tip factor only just clearing the screen), giving the repair loop a reason to
    add margin or stop. Pass-side only, so it never double-signals an existing
    warning. (Always-on positive confirmations were left out as noise — the INFO
    near-miss is the actionable half, and Tier 2's `observed`/`limit` make a UI
    margin gauge free without emitting on every pass.)

*The shelf-joint subset of #9 (one small schema field) is ✅ DONE:*

9a. ✅ **`STRUCT-014` shelf-to-side joint + `MOVE-003` solid panel float gap**
    (§5.4) — added a `ShelfJoint` enum and a `CabinetSpec.shelf_joint` field
    (default `pins` → zero golden churn). `STRUCT-014` (WARN) flags a `screw`/
    `butt` load shelf; a fixed `dado`/`cleat` shelf also flows through to the
    joinery schedule as a housing op. `MOVE-003` (WARN, validator-only — no new
    schema) flags a **solid** floating door panel (the cut list sizes the panel
    to fill the groove with no expansion allowance); it stays quiet on the common
    plywood shaker panel, which doesn't move.

    While scoping this, two of the §4.3 batch turned out **moot** under today's
    DSL and were deliberately *not* emitted (faking them would be dead code):
    `STRUCT-040`/`STRUCT-041` (full-enclosure) — `BackStyle` has no open/none
    option, so a cabinet always has a back/sides/bottom/top; and `GRAIN-003`
    (over-wide single board) — the cut list already auto-glues-up any solid panel
    wider than a board, so the defect can't arise.

*Still blocked (need a §5 schema PR each):*

9b. **`MOVE-005` (cross-grain glue), `GRAIN-002`/`GRAIN-004` (grain orientation /
    mixed sawn)** — need the per-part/per-stave grain model (§5.5): grain is one
    top-level enum today, and glue-up staves carry only a count, no per-stave
    sawn orientation. **`MOVE-004`** (breadboard slotting) needs a breadboard-end
    feature. **`DIM-001`/`DIM-002`** need a table sub-type. The **`STD-*`**
    meta-rules round out the gap. These should sequence behind a small DSL-schema
    PR each.

Tiers 1–2 are behavior-preserving except the two explicit additions and should
land with drift-guard tests keyed by the new `rule_id`. Tier 3 items that depend
on §5 (load model, part-to-part joints, per-part grain) should sequence behind a
small DSL-schema PR each.

---

*Reviewed against `validator.py`, `engineering.py`, `dsl_lint.py`, `dsl.py`,
`furniture_types.py`, and the `validation-rules.md` / `design-principles.md`
catalog. No `TODO`/`FIXME`/stub markers exist in the diagnostics code — the gaps
above are silent omissions, not flagged ones.*
