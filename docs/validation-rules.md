# Compiler Validation Rule Catalog

The concrete checks the Woodworking AI compiler should run against a design.
Rationale and sources for every threshold are in
[`design-principles.md`](./design-principles.md).

Each rule has: a stable **ID**, a **severity** (ERROR / WARN / INFO), the
**applies-to** scope, the **condition** that triggers a diagnostic, and the
**message/fix**. IDs are grouped by category prefix so rules can be referenced,
suppressed (`// noqa: STRUCT-014`), and unit-tested individually.

Severity recap:
- **ERROR** — physically won't build, will fail structurally, or violates a
  mandatory safety standard. Blocks compilation.
- **WARN** — best-practice / longevity / voluntary-standard violation.
- **INFO** — advisory (proportion, comfort range, efficiency).

A rule's `condition` is written in pseudo-expression form against a design model
with parts, joints, materials, and a declared `intent` (table, chair, base
cabinet, dresser, bookshelf, …).

---

## DIM — Dimensional & ergonomic

| ID | Sev | Applies to | Condition (flag when…) | Message / fix |
|---|---|---|---|---|
| DIM-001 | WARN | dining table | `top_height ∉ [28,30] in` | Dining table height outside 28–30 in standard. |
| DIM-002 | WARN | counter/bar table | counter `∉[34,36]`, bar `∉[40,42]` | Surface height off standard counter/bar range. |
| DIM-003 | WARN | chair/stool | `seat_height ∉ [18,20]` (dining) | Seat height outside comfortable range for class. |
| DIM-004 | **ERROR** | table + seating set | `top_height − paired_seat_height ∉ [9,13]` | Insufficient/excess thigh clearance; seat & top mismatched (need ~10–12 in). |
| DIM-005 | WARN | desk | `work_height ∉ [28,30] in` or `depth < 30 in` | Desk height/depth outside ergonomic range. |
| DIM-006 | INFO | any seating | knee clearance under apron `< 10 in` | Apron too low; legs won't fit. |
| DIM-007 | WARN | base cabinet | `depth ≠ 24` or `box_height ≠ 34.5` (±tol) | Non-standard base cabinet dimension. |
| DIM-008 | WARN | wall cabinet | `depth ≠ 12` or height ∉ {12,15,18,21,24,30,36,42} | Non-standard wall cabinet dimension. |
| DIM-009 | WARN | cabinet | `width mod 3in ≠ 0` (frameless: off 32 mm grid) | Width breaks the manufacturing increment. |
| DIM-010 | WARN | bookshelf | clear shelf opening height `< 8 in` or `> 14 in` | Shelf spacing outside useful range; consider adjustable. |

---

## PROP — Proportion (advisory)

| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| PROP-001 | INFO | any case/top | primary rectangle ratio far from 1.618 (e.g. `|ratio−1.618| > 0.4` and not a deliberate square) | Consider golden-ratio proportions for visual balance. |
| PROP-002 | INFO | leg vs. mass | leg cross-section visually too thin/thick for span | Leg proportion looks under/over-scaled. |
| PROP-003 | INFO | drawer bank | drawer-height progression irregular | Consider graduated (e.g. golden-ratio) drawer heights. |

---

## STRUCT — Structural integrity

### Racking / base stability
| ID | Sev | Applies to | Condition | Message / fix |
|---|---|---|---|---|
| STRUCT-001 | **ERROR** | table/desk/chair base | leg↔rail joint type ∈ {butt, pocket-screw-only} **and** no apron **and** no stretchers | Base has no racking resistance; add apron/stretchers or upgrade to M&T/dowel. |
| STRUCT-002 | WARN | table/desk | apron present but leg↔apron joint is pocket-screw-only | Pocket screws give poor racking resistance for leg-to-apron; prefer M&T/dowel + corner blocks. |
| STRUCT-003 | WARN | tall/long base (height>30in or span>48in) | aprons only, no lower stretchers | Add stretchers for racking on tall/long base. |
| STRUCT-004 | INFO | leg frame | no corner blocks at apron corners | Corner blocks improve rigidity and allow top attachment. |

### Joint selection by load
| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| STRUCT-010 | **ERROR** | any load-bearing joint | joint in primary load path is `butt` with glue only and load is tension/shear | Butt joint cannot carry tension/shear; choose an interlocking/mechanical joint. |
| STRUCT-011 | WARN | drawer corners | joint ∉ {dovetail, box, locking rabbet} | Drawer corners should use dovetail/box/locking joint for pull-open loads. |
| STRUCT-012 | **ERROR** | drawer (dovetailed) | dovetail orientation does not resist the open-pull direction | Tails oriented wrong; reorient so interlock resists drawer being pulled open. |
| STRUCT-013 | INFO | biscuit used structurally | biscuit relied on for strength (not just alignment) | Biscuits are alignment aids, not structural; don't count on their strength. |
| STRUCT-014 | WARN | shelf into case side | shelf joint is butt/screw only for a load shelf | Use dado/rabbet (+glue/fastener) so the shelf is captured in shear. |

### Shelf sag / deflection
| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| STRUCT-020 | **ERROR** | shelf | computed deflection `> span/360` at design load | Shelf exceeds engineering deflection limit; shorten span, thicken, or add support. |
| STRUCT-021 | WARN | shelf | deflection `> 0.03 in × span_ft` (visible-sag limit) | Sag will be visible; consider stiffer material/shorter span. |
| STRUCT-022 | WARN | ¾-in plywood shelf | unsupported span `> 30 in` (or `>24 in` at heavy load) | Span too long for ¾ ply; add center support or thicker/stiffer stock. |
| STRUCT-023 | INFO | shelf | material E low for span (e.g. particleboard over 24 in) | Low-stiffness material over long span; expect sag. |

*Deflection model:* compute from span (∝ length³), load distribution,
thickness (∝ thickness³), and material Young's modulus E (maple≈1.83M,
oak≈1.8M, plywood≈1.5M psi). Design load: bookshelf ≈ 20–40 lb/ft (use 35 for
library). This is the "Sagulator" calculation.

### Stability / tip-over (regulated)
| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| STRUCT-030 | **ERROR** | clothing storage unit (≥27 in tall, ≥30 lb, >3.2 ft³) | fails ASTM F2057 stability model (tips when top drawer loaded & extended) OR no anti-tip provision | Unit risks tip-over; meet ASTM F2057-23, provide anti-tip restraint + marked wall-attach point. |
| STRUCT-031 | WARN | tall narrow casework (height/depth ratio high) | center of gravity high / shallow base | Tip-over risk; widen/deepen base, lower CG, or require wall anchor. |
| STRUCT-032 | INFO | freestanding tall unit | no documented wall-anchor hardware point | Add a marked anti-tip attachment point. |

### Casework enclosure (KCMA)
| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| STRUCT-040 | WARN | wall cabinet | missing any of back/bottom/sides/top | Cabinet should be fully enclosed (KCMA A161.1). |
| STRUCT-041 | WARN | base cabinet | missing back/bottom/sides | Base cabinet not fully enclosed. |
| STRUCT-042 | WARN | floor cabinet | toe space `< 2 in deep` or `< 3 in high` | Toe kick below KCMA minimum. |
| STRUCT-043 | INFO | wall cabinet | mounting can't carry rated load (KCMA tests to 600 lb) | Verify hanging method/back thickness for load. |

---

## MOVE — Wood movement & grain (solid wood)

These are the highest-value "silent failure" checks.

| ID | Sev | Applies to | Condition | Message / fix |
|---|---|---|---|---|
| MOVE-001 | **ERROR** | solid panel locked on all edges | wide solid panel glued/fixed across grain at both ends (e.g. glued breadboard, panel glued into frame) | Cross-grain restraint will split the wood; let the panel float / slot the joint. |
| MOVE-002 | **ERROR** | tabletop attachment | top fastened to base with a rigid screw grid across the width | Top can't move; use figure-8 / Z-clips / slotted cleats. |
| MOVE-003 | WARN | frame-and-panel | panel sized with no expansion gap in groove | Leave float gap: ~¼ in/12 in (flatsawn), ⅛ in/12 in (quartersawn). |
| MOVE-004 | WARN | breadboard end | peg holes not elongated/slotted (center pinned, ends slotted) | Slot outer peg holes so the end can slide. |
| MOVE-005 | WARN | cross-grain glue | two parts glued with grains running perpendicular over significant length | Differential movement will crack; redesign as floating/mechanical. |
| MOVE-006 | INFO | movement allowance | allowance computed without accounting for flat vs. quarter sawn | Refine allowance using grain cut (quartersawn ≈ half the movement). |

---

## GRAIN — Grain direction & glue

| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| GRAIN-001 | **ERROR** | glue-only joint | joint is end-grain to end-grain with no mechanical reinforcement | End-grain glue joints are weak; add M&T/dowel/spline or redesign long-grain to long-grain. |
| GRAIN-002 | WARN | structural part (leg/rail/shelf) | grain runs across the short dimension | Orient grain along the long/structural axis for strength. |
| GRAIN-003 | WARN | wide solid part | single board wider than available stock implied | Glue up narrower boards (long-grain edges) rather than running cross-grain. |
| GRAIN-004 | INFO | panel glue-up | mixed flatsawn/quartersawn edges glued together | Keep grain orientation consistent to avoid differential movement/cracking. |

---

## MAT — Material & buildability

| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| MAT-001 | **ERROR** | any sheet part | thickness references nominal but joinery (dado) cut to nominal not actual (¾→23/32) | Cut joinery to *actual* sheet thickness; nominal will be loose. |
| MAT-002 | WARN | sheet part | required panel exceeds standard sheet (e.g. dimension >96 in on 4×8) | Part won't yield from a standard 4×8 sheet; seam or change material. |
| MAT-003 | **ERROR** | solid part | finished thickness > rough stock can yield after S2S (lose ~3/16 in/face) | Chosen rough stock too thin for finished dimension; step up (e.g. 4/4→5/4). |
| MAT-004 | INFO | sheet layout | poor nesting / high waste on 4×8 | Optimize part nesting to reduce sheet waste. |
| MAT-005 | INFO | material vs. role | low-stiffness/low-durability material in a high-wear/high-load role | Reconsider material for the role (e.g. particleboard shelf, softwood drawer runner). |

---

## HW — Hardware & clearance

| ID | Sev | Applies to | Condition | Message / fix |
|---|---|---|---|---|
| HW-001 | **ERROR** | drawer w/ side-mount slides | `(opening_width − drawer_box_width)/2 ≠ 0.5 in` (within +1/32/−0) | Slide clearance wrong; drawer box width must be opening − 1 in. |
| HW-002 | **ERROR** | drawer | slide length > available case depth, or box deeper than slide travel | Slide/box depth mismatch; drawer won't seat or fully extend. |
| HW-003 | WARN | drawer | inset drawer depth not reduced for face/frame | Inset reduces usable depth; recompute box length. |
| HW-004 | WARN | doors | door reveal/gap inconsistent or `< 1/16 in` (doors may bind) | Set consistent reveals; overlay doors must not collide. |
| HW-005 | WARN | door w/ concealed hinge | stile narrower than 35 mm cup bore needs | Stile too narrow for hinge cup; widen or change hinge. |
| HW-006 | INFO | drawer | extension type vs. access need (¾ vs full vs over-travel) | Confirm extension class matches required access. |

---

## STD — Standards / class compliance (meta-rules)

| ID | Sev | Applies to | Condition | Message |
|---|---|---|---|---|
| STD-001 | WARN | kitchen/vanity cabinet | design not checked against ANSI/KCMA A161.1 set | Run the KCMA enclosure/toe-kick/load checks (STRUCT-040…043). |
| STD-002 | **ERROR** | clothing storage unit | in-scope for ASTM F2057-23 but no stability/anti-tip provision | Mandatory CPSC standard; see STRUCT-030. |
| STD-003 | INFO | commercial/office furniture | not checked vs. ANSI/BIFMA durability tests | Consider BIFMA strength/durability validation for commercial use. |
| STD-004 | INFO | architectural casework | not checked vs. AWI/AWS quality grades | Validate against AWI Architectural Woodwork Standards grade. |

---

## Implementation status

These rules are wired into the engine today (`src/woodworking_ai/validator.py`,
backed by the calculators in `src/woodworking_ai/engineering.py`):

| Rule(s) | Where | Notes |
|---|---|---|
| STRUCT-020/021/022 | `evaluate_shelf` → cabinet shelves | Beam deflection vs. span/360 (error) and visible-sag limit (warning); stiffness from `shelf_species`. |
| STRUCT-030/031 | cabinet tip-over (DRESSER/TALL) | Warns when a unit ≥686 mm has no `anti_tip`, and when tall+shallow (depth/height < 0.40). |
| STRUCT-042 | toe-kick minimums | Warns below ~75 mm high / ~50 mm deep (KCMA). |
| MOVE-001/002 | table `top_fixing` | Error on a rigidly fixed solid top; warns the seasonal allowance for floating tops. |
| STRUCT-010 | carcass `joinery` | Warns on a glued butt carcass joint. |
| STRUCT-011 / GRAIN-001 | drawer `corner_joint` | Warns on weak (butt/dowel) drawer corners; flags the end-grain butt joint specifically. |
| STRUCT-002 | table `joinery` | Warns when a pocket/butt/screw leg-to-apron joint resists racking poorly. |
| HW-001 | drawer `slide_clearance` / `slide_type` | Warns when side-mount clearance isn't ~12.7 mm; errors when the opening leaves no usable box. |
| HW-002 | drawer `slide_length` | Errors when the slide is longer than the cabinet is deep. |
| HW-005 | door thickness / width | Errors when a door can't host a 35mm concealed hinge cup (too thin for the 12.5mm bore, or too narrow for the 40mm footprint); warns when marginal. |
| MAT-001 | `material.*` thickness | Warns on thicknesses that aren't stocked sheet goods (`stock.py`). |
| MAT-002 | carcass panel size | Warns when a panel won't yield from a standard 2440×1220 sheet. |
| MAT-003 | table `top_thickness` | Warns when a solid top is thicker than 12/4 stock surfaces to. |
| PROP-001 | cabinet face / table top | INFO when the primary rectangle is far from any pleasing ratio; suggests golden-ratio dimensions (`proportion.py`). |
| PROP-002 | table `leg` | INFO when the leg is spindly or chunky for the table height. |
| PROP-003 | drawer bank | INFO when 3+ drawer heights are neither uniform nor graduated. |
| STRUCT-012 | drawer `dovetail_tails` | Errors when a front dovetail's tails aren't on the drawer sides (the front could pull off). |
| DIM-009 | shelves vs. 32mm system | Warns when the box is too short to drill a 32mm-system pin column, or too shallow for two pin rows; `grid_violations()` verifies a schedule against the 32mm grid. |
| MAT-006 | `shelf_species` not in the stiffness DB | Warns when a shelf species name resolves to neither the wood database nor the sheet-goods map, so the sag check fell back to plywood silently. |
| MAT-007 | `species` vs `shelf_species` | INFO when the piece is a solid wood but the sag check used the plywood default — prompts setting `shelf_species` so the two cooperate. |
| HW-007 | heaviest single part (`mass.py`) | WARN when one **assembled** part exceeds the ~25 kg one-person lift (weight from the cut list × species/sheet density; glue-up staves are summed back to the panel so a heavy solid top isn't hidden behind its boards); suggests knock-down joinery or a second person. New rule (not in the original catalog). |
| STRUCT-043 | wall cabinet self-weight (`mass.py`) | INFO that a wall cabinet's estimated mass hangs on its fixing — screw a rail/cleat into studs and use a stout back (KCMA rates to ~270 kg). |
| DIM-003 | bench/stool `height` | WARN when the seat height is outside the bench/stool range. (No seating sub-type in the DSL — covered by range; a chair-vs-stool mismatch is caught relationally by DIM-004.) |
| DIM-004 | project: table top ↔ paired seat | WARN (not the catalog's ERROR) when a seat and its **best-matched** table in a project leave a thigh gap outside ~228–330 mm. Only sit-at-height tables are pairing targets (a coffee/side table beside a bench isn't a mismatch); best-fit pairing avoids cross-flagging a counter's stools against a dining table. Softened to WARN because the DSL has no explicit seat↔table link, so the pairing is inferred — and a seat whose true partner isn't modelled may still be matched to another table. |
| DIM-005 | desk `height` / `depth` | WARN when desk height is outside ~680–800 mm, or depth is under ~500 mm (cramped for a work surface). |
| DIM-006 | table/desk apron underside | INFO when a sit-at surface's apron underside is below ~600 mm — tight knee room for a seated user. Only checked on sit-at-height pieces (a coffee table is exempt). |
| DIM/STRUCT (existing) | `validate` | Dimensional bounds, opening fit, door/drawer fit, per-type sanity were already present pre-audit. |

**Near-miss advisories.** A *passing* structural check whose measured value is
within 10% of its limit also emits a pass-side INFO (shelf sag approaching the
visible limit → `STRUCT-021` INFO; tip factor only just clearing the screen →
`STRUCT-031` INFO). It reuses the parent rule id at INFO severity, fires only on
the pass side (never doubling an existing warning), and gives the repair loop a
reason to add margin — or to stop, knowing a check passed comfortably.

`info`-severity advisories never affect `ValidationResult.ok` (so they never
trigger the designer's repair loop) and are surfaced separately via
`ValidationResult.infos` and the API's `advisories` field.

**Rule IDs are now attached to emitted diagnostics** (`Issue.rule_id`), not just
to these tables — query them with `ValidationResult.by_rule("STRUCT-020")` for
suppression/audit by stable ID. The rendered feedback string is unchanged (the ID
is programmatic only). The high-value structural / hardware / movement / material
/ proportion / dimensional rules are tagged; bare type/bound checks have no ID.

**Numeric rules are also machine-actionable.** Beyond the prose `message`, a
computed rule carries a structured record so the repair loop can compute the exact
edit instead of regex-parsing English, and a UI can render a gauge or an
action-button:

| Field | Meaning | Example |
|---|---|---|
| `observed` | the measured value the rule judged | `3.4` |
| `limit` | the threshold it was judged against | `2.5` |
| `units` | unit of `observed`/`limit` | `"mm"` |
| `direction` | which way `observed` violated `limit`, so the loop knows how to converge without rule knowledge | `"max"` |
| `fix` | the imperative remedy, split out of the prose | `"thicken or shorten the span"` |
| `doc_anchor` | deep link into `design-principles.md` for the rule | `"design-principles.md#33-shelf-sag--deflection"` |

`direction` disambiguates rules where *bigger* is worse (sag) from rules where
*smaller* is worse (tip-over stability) — without it, `(observed, limit)` alone
can't tell a repair loop which way to edit:

- `"max"` — `observed` must end `<= limit`; **reduce** observed (e.g. sag).
- `"min"` — `observed` must end `>= limit`; **increase** observed (e.g. tip
  factor, door backing, toe-kick height).
- `"target"` — drive `observed` **toward** `limit`, a nominal/band (e.g.
  side-mount slide clearance).
- `""` — `limit` is an informational trigger, not a convergence target (e.g.
  MOVE-002's absolute "a rigidly fixed top will crack"), so don't optimise it.

These are populated on the numeric rules (STRUCT-020/021, STRUCT-031, MOVE-001/002,
HW-001/002/005, DIM-007/008/010, MAT-002, single-door width) and left empty on
bare type/range checks, so a consumer can tell a *computed* rule from a plain
bound. The web `build_result` bundle serialises every populated field; empty ones
are omitted so unstructured issues stay compact.

**One diagnostic shape across layers.** `validator.Issue` and `dsl_lint.LintIssue`
now both satisfy the `diagnostics.Diagnostic` protocol (`severity`, `field`,
`message`, `rule_id`), so the designer loop can fold parse-time lint and
validation issues into one stream and filter by stable ID. A dropped-key lint
reports `severity="warning"` and `rule_id="LINT-001"`; `Severity` itself moved to
the shared `diagnostics` module (still re-exported from `validator`).

| LINT-001 | WARN | any spec | a key the tolerant loader will silently drop (typo'd field) | Unknown field ignored; surfaced with a "did you mean" suggestion. |

Backed by the `stock.py`, `proportion.py`, and `drilling.grid_violations`
helpers. The structural calculators, the hardware/joinery feasibility checks, and
the engineering rules in the "Implementation status" table above are implemented
and tested (`tests/test_engineering.py`, `test_joinery_hardware.py`,
`test_proportion.py`, `test_hinges.py`, `test_grid_dovetail.py`,
`test_dsl_diagnostics.py`, `test_mass.py`, `test_ergonomics.py`). **Not every
catalogued rule has a runtime emitter yet.** Now wired (Tier 3): the seat↔top
coupling `DIM-004`, seat/desk heights `DIM-003`/`DIM-005`, knee clearance
`DIM-006`, weight/handling `HW-007`/`STRUCT-043`. Still open:
- `DIM-001`/`DIM-002` (dining/counter/bar **table** heights) — **blocked**: the
  DSL has no table sub-type, so a 450 mm coffee table can't be told from an
  under-height dining table; flagging by absolute height would false-positive.
  Needs a `table` sub-type field (a §5 DSL gap) before it can be wired.
- several `MOVE`/`GRAIN`/`STRUCT` enclosure rules (need part-to-part joints) and
  the `STD-*` meta-rules.

See [`DSL_DIAGNOSTICS_REVIEW.md`](./DSL_DIAGNOSTICS_REVIEW.md) §4.3 / §5 for the
remaining gap list and the schema work each needs.

## Implementation notes for the compiler

1. **Intent drives the rule set.** Each `intent` (table, chair, base-cabinet,
   wall-cabinet, dresser, bookshelf, desk…) activates a subset of rules. Resolve
   intent first; unknown intent → run only universal STRUCT/MOVE/GRAIN/MAT rules.

2. **Coupled-dimension checks need the assembly, not parts.** Rules like
   DIM-004 (seat↔top) and HW-001 (opening↔box) compare *related* parts —
   build the reference graph in an early pass.

3. **Numeric thresholds belong in a data table, not code.** Keep all magic
   numbers (heights, clearances, E values, movement coefficients) in a single
   versioned config so standards updates don't touch logic. Treat the values
   here as defaults pending direct confirmation against the cited standards.

4. **Three structural calculators are first-class:**
   - *Sagulator* (STRUCT-020…023): beam deflection.
   - *Movement* (MOVE-*): `Δ = width × MC_change% × shrinkage_coeff`, cut-aware.
   - *Tip-over* (STRUCT-030): CG + drawer-load moment vs. base footprint.

5. **Severity is suppressible but auditable.** Allow per-rule suppression with a
   reason; ERROR-level safety rules (STD-002 / STRUCT-030) should require an
   explicit override acknowledgment.

6. **Every diagnostic carries a fix hint.** The "Message / fix" column is the
   model for actionable output — say what's wrong *and* the standard remedy.

> ⚠️ The numeric thresholds here are engineering rules-of-thumb and summaries of
> published standards, suitable for design-time linting. They are **not** a
> substitute for the actual ANSI/KCMA A161.1, ASTM F2057, ANSI/BIFMA, or AWI
> documents when certification or regulatory compliance is required.
