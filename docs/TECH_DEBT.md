# Tech Debt — Woodworking AI (living doc)

> **This is the single living tech-debt doc.** It supersedes three earlier audits,
> now in [`archive/`](archive/): `TECH_DEBT_AUDIT.md`,
> `TECH_DEBT_AUDIT_INTEGRATION.md`, and the `TECH_DEBT_CLEANUP_PLAN.md` that
> executed them. Keep *this* file current — mark findings fixed inline and
> re-baseline here rather than spawning a new dated audit doc.

> **Last audit:** 2026-06-26 · **Branch:** `claude/tech-debt-audit-rfbici` (off `master`)
> **Scope:** `src/woodworking_ai/**` (~17.9k LOC, 50 modules) + `static/index.html`
> (2.4k lines) + `tests/**` (73 files, ~9.3k LOC) + packaging/CI/docs.
> **Method:** five parallel deep-reads (duplication, architecture, anti-patterns,
> testing, web/CLI/packaging/security), **each finding re-verified against the
> current code with `file:line` quotes**. Skeptical re-check of the three prior
> audit docs — claims marked "fixed" there were spot-verified, not trusted.

## How this audit relates to the prior ones

The three earlier docs are archived under [`archive/`](archive/)
(`TECH_DEBT_AUDIT.md`, `TECH_DEBT_AUDIT_INTEGRATION.md`,
`TECH_DEBT_CLEANUP_PLAN.md`). **The bulk of what they claim was fixed is genuinely
fixed** — credit where due:

- Spec-type `isinstance` ladder centralised in `dispatch.spec_kind()` and a
  `furniture` leaf registry (real, load-bearing for 5 of the pipeline stages).
- Slide-clearance / `SYSTEM_PITCH` / hinge-cup constants unified in `constants.py`.
- Drawer-box dims share `partmath.drawer_box_dims`; PDF boilerplate shares
  `pdf_common.py`; LLM JSON extraction shares `llm.extract_json`.
- `web.py` parse-error info leak closed; XSS escaping (`esc()`) applied; LLM-cost
  params clamped; private cross-module imports mostly promoted to public APIs.

This audit is the **next layer**: residual debt, plus **new debt introduced by the
very refactors that fixed the old debt** (a regressed magic number, a god-module,
a triplicated taxonomy) as the codebase grew from 5 furniture types to 13.

**Overall verdict:** a well-architected, well-tested codebase. The findings below
are real but mostly localized; none is a crisis. The single highest-leverage fix
is collapsing the three parallel type registries (HIGH-2).

---

## Remediation log

> Tracked inline so this living doc stays current. ✅ = fixed on
> `claude/tech-debt-audit-rfbici`.

**Tier 1 — correctness (all ✅):**
- ✅ **1.1** validator now emits a "could not verify" warning when a safety
  schedule fails, instead of silently skipping the check.
- ✅ **2.1** legged drawer boxes route through `partmath.drawer_box_dims`; the
  regressed `clear = 13.0` / 25 mm drop are gone.
- ✅ **1.2** the 5-piece door formula is single-sourced in
  `partmath.door_panel_dims` (model = visible opening, cut list = opening + tongue);
  outputs byte-identical, drift-guarded.

**Tier 2 — guardrails (all ✅):**
- ✅ ruff widened `F` → `F + B` (bugbear); 20 surfaced violations fixed.
- ✅ **5.1** a scheduled+manual `cad` CI job installs build123d so the
  geometry/export suite is actually gated.
- ✅ **5.3** shared `tests/factories.py` (`cab` / `cab_with_drawer`); the four
  identical `_cab` builders migrated (rest are bespoke, left as-is).
- ✅ **5.2** redirected: `furniture_types.py` was already 95% covered (audit
  premise stale); the real gap was `cli.py` at 9% → ~78% via `tests/test_cli.py`,
  and the CLI now reports a clean error on bad/missing spec JSON (the **H3** fix).

**Still open** (next up): the structural Tier-3 items — collapse the triplicated
taxonomy (HIGH-2), bring drilling/estimator under the registry (HIGH-2 §3.2),
split the `furniture_types.py` god-module (HIGH-3), `LeggedSpec` base (MED-2), and
the god-function decompositions (#7).

---

## Headline findings

| # | Issue | Severity | Status | Where |
|---|---|---|---|---|
| 1 | **Validator silently skips two safety checks** when a schedule raises (reports unsafe as safe) | HIGH | ✅ fixed | `validator.py:278-281, 317-320` |
| 2 | **Furniture taxonomy is triplicated** — `KNOWN_KINDS` + `spec_kind` + `_spec_from_dict` hand-synced | HIGH | open | `dsl.py:1708,1763-1789`; `dispatch.py:51-74` |
| 3 | **Regressed magic number** — legged-furniture drawer boxes use `clear = 13.0`, the exact conflict the cleanup "killed" (`12.7`) | HIGH | ✅ fixed | `furniture_types.py:1426` |
| 4 | **Door-panel formula computed twice and disagrees by 20 mm** — 3D model vs cut list | HIGH | ✅ fixed | `geometry.py:595-596` vs `cutlist.py:482,487-488` |
| 5 | **CAD geometry & exporters have zero CI coverage** — 23 build123d tests skipped every run | HIGH | ✅ fixed | CI + `tests/test_*` |
| 6 | **`furniture_types.py` is a 2088-line god-module** holding 9 types under a 2nd convention | HIGH | open | `furniture_types.py` |
| 7 | **God functions** — `_validate_cabinet` (321 lines), `build_result` (261), `critique` | HIGH/MED | open | `validator.py:370`, `service.py:294` |

---

## 1. Correctness debt (HIGH)

### 1.1 Validator silently disables safety checks on any schedule error
`validator.py:278-281` and `validator.py:317-320`:
```python
try:
    sched = joinery_schedule(spec)
except Exception:
    sched = None
...
if sched is not None:        # short-grain blow-out check skipped silently if None
```
The same pattern wraps `drilling_schedule(spec)` for the drawer-slide-vs-shelf-pin
collision check. If either schedule raises **for any reason**, the input becomes
`None`, the safety loop is skipped, and the function returns **with no warning** —
a broken schedule makes the cabinet look safe. This is the "report a failure as
no problem" anti-pattern in a *safety* path.

**Fix:** Catch the specific expected exception and, on failure, append an
`Issue("warning", ..., "could not verify X")` instead of dropping the check —
the degrade-with-warning contract `critic._brep_interferences` and `builder.py`
already model correctly (`log.warning(..., exc_info=True)` before degrading).

### 1.2 Door-panel dimensions computed twice, disagree by 20 mm
The 5-piece-door *constants* are shared (`DOOR_STILE_WIDTH`, `DOOR_PANEL_GROOVE`),
but the *formula* using them is not:
- Cut list adds the groove tongue — `cutlist.py:487-488`:
  `panel_w = d0.width - 2*DOOR_STILE_WIDTH + 2*DOOR_PANEL_GROOVE`
- Geometry omits it — `geometry.py:595-596`: `inner_w = max(w - 2*stile, 10.0)`

So the rendered/exported 3D panel is `2*DOOR_PANEL_GROOVE = 20 mm` smaller in each
axis than the panel the cut list tells the shop to cut. This is exactly the
"dimension computed in two places that can drift" pattern the architecture doc
claims is eliminated — half-fixed (constants shared, formula not).

**Fix:** Add `partmath.door_panel_dims(width, height, *, groove)` mirroring
`drawer_box_dims`, and call it from both `cutlist._door_parts` and
`geometry._door_leaf_panels`. Decide once whether the modeled panel includes the
tongue.

---

## 2. Duplication & single-source-of-truth (HIGH/MED)

### 2.1 Regressed slide-clearance magic number in the legged-furniture path (HIGH)
The prior cleanup's headline fix was unifying slide clearance to
`SLIDE_SIDE_CLEARANCE = 12.7` (`constants.py:16`). **The legged-furniture drawer
builder never adopted `partmath` and re-introduces the retired `13.0`** —
`furniture_types.py:1424-1428`:
```python
bt = 12.0                       # box wall thickness   (vs material.drawer_box)
bottom_t = 6.0
clear = 13.0                    # side-mount slide clearance each side  (vs 12.7)
box_h = max(front_h - 25.0, 60.0)   # vs DRAWER_BOX_HEIGHT_DROP=40.0
box_w = max(opening_w - 2 * clear, 80.0)
```
Nightstand/desk/workbench drawer boxes come out 0.6 mm narrower per side and
dropped 25 mm vs 40 mm below the front — silently diverging from every cabinet
drawer, the constant, the validator's `10–14mm` warning band, and the
`test_techdebt.py` drift guards. Box-wall (`12.0`) and bottom (`6.0`) thicknesses
are hardcoded here too, instead of reading `material.drawer_box`.

**Fix:** Have `_drawer_cut_parts` call `partmath.drawer_box_dims(...)` and read
wall/bottom thickness from the material; delete the local arithmetic. This is the
cleanest concrete win in the audit — it closes a real regression.

### 2.2 Per-species board-foot price duplicated and already drifting (MED)
Two tables key off the same species vocabulary:
- `species.py:54-101` — canonical `_TABLE`, each `Species` carries `price_per_bdft`.
- `estimator.py:61-65` — `species_board_foot_price` re-types the same numbers.

`_board_foot_price` (`estimator.py:138-145`) consults the PriceBook dict **first**,
so on disagreement the duplicate silently wins. **Already desynced:** `species.py`
defines `alder`, `soft_maple`, `hard_maple`; the estimator dicts instead have
`maple`, `birch`, `beech`. The two "sources of truth" for wood vocabulary have
diverged.

**Fix:** Make `species_board_foot_price` default to `{}` (pure user override) and
derive the base from `species.price_per_bdft`. Drive `species_multiplier`'s keys
off `species.all_names()`.

### 2.3 The "box = opening − 2·clearance" rule lives in four places (LOW)
`partmath.py:30`, `furniture_types.py:1428`, `validator.py:569`, `hardware.py:93`.
The validator/hardware copies are *defensibly* distinct (configurable per-drawer
clearance; undermount branch), so this is not a clean copy-paste — but the core
relationship is asserted four times. Route the side-mount case through one helper.

---

## 3. Architecture & extensibility (HIGH/MED)

### 3.1 Furniture taxonomy is triplicated and hand-synced (HIGH)
Adding a furniture type still requires coordinated edits across three independent
registries that encode the *same* taxonomy:
1. `dsl.py:1708` — add the string(s) to the hand-maintained `KNOWN_KINDS` frozenset.
2. `dsl.py:1763-1789` — add an arm to the 13-branch `_spec_from_dict` `if kind ==`
   ladder.
3. `dispatch.py:51-74` — add a module constant **and** an arm to the parallel
   13-branch `spec_kind` isinstance ladder.

Plus the spec dataclass (`dsl.py`), the 5 `register(...)` stages
(`furniture_types.py`), and a manual `DSL_SCHEMA_HINT` example (`dsl.py:1818`).
The dispatch refactor moved the ladder from ~12 stages to ~3 chokepoints — real
progress — but "no stage edits / plugs into the whole pipeline" overstates it: a
missing arm in any of the three fails *differently* (unknown-kind error,
mis-dispatch to cabinet, or `KeyError`).

**Fix (highest leverage):** Drive all three from one self-registering table — a
`@register_spec("nightstand")` decorator or a `SPEC_CLASSES` dict in `dsl.py` that
maps `kind ↔ class`. Derive `KNOWN_KINDS` and `_spec_from_dict` from it, and
replace `spec_kind`'s isinstance ladder with a `type(spec)` lookup. Generate the
schema-hint type menu from the same table. This also unblocks 3.3.

### 3.2 Two pipeline stages bypass the registry and dispatch on cabinet-shaped labels (HIGH)
The leaf registry covers exactly 5 stages
(`_STAGES = ("panels","cut_parts","validate","joinery_ops","assembly")`,
`furniture.py:76`). **Drilling and estimator are not registry stages.**
`drilling_schedule` reverse-engineers behavior from panel *label strings* only
cabinets emit — `drilling.py:173-180`:
```python
sides = [p for p in panels if p.label.startswith("Side")]
doors = [p for p in panels if p.label == "Door" or p.label.startswith("Door ")]
```
A new type gets no boring unless it emits cabinet-identical labels; a stray label
collision bores holes invisibly. The "registry = whole pipeline" abstraction leaks.

**Fix:** Add `drilling_ops` as a 6th registry stage, or carry a typed
`PanelRole` enum on `PanelBox` (e.g. `SIDE_LEFT`, `DRAWER_FRONT`) that drilling
matches on instead of `label.startswith(...)`.

### 3.3 `furniture_types.py` is a 2088-line god-module under a competing convention (HIGH)
The registry deliberately supports **two** registration conventions
(`furniture.py:25-44`): *distributed* (cabinet, table — each stage in its home
module) and *co-located* (the other 9 types — all stages in `furniture_types.py`).
Canonizing both as "intentional" means a developer adding type #14 has no
canonical example: cabinet says "edit 5 modules," box says "add to the 2000-line
file." The `err`/`warn` validation-closure boilerplate recurs at **10 sites**
(`furniture_types.py:152, 325, 536, 756, 1066, 1279, 1453, 1590, 1793, 1993`).

**Fix:** Split `furniture_types.py` into one module per type
(`furniture_types/box.py`, …). Hoist `err`/`warn` into a shared `IssueCollector`.
Pick one convention as the documented standard.

### 3.4 Five "legged" types duplicate fields and panel/cutlist math (MED)
`TableSpec`, `BenchSpec`, `NightstandSpec`, `DeskSpec`, `WorkbenchSpec` all model
"top + 4 legs + aprons" with no shared base — the same ~9 fields repeat verbatim
(`dsl.py:911-936` vs `1259-1290`). The code itself flags it (`dsl.py:905-906`:
*"the shared base is a follow-up"*). Worse, the *implementation* is split across
two modules and two conventions (table's legged math in `geometry.py`/`cutlist.py`;
the other four in `furniture_types.py`), so a leg-joinery change must be made up to
5 times and table will be forgotten.

**Fix:** A `LeggedSpec` mixin/base for the shared fields + one
`legged_panels()/legged_cutlist()` helper all five call.

### 3.5 Layering inversion + ~30 lazy in-function imports (MED)
`dsl.py:1665` (the foundation layer) imports *up* into geometry:
`from .geometry import local_plan_bounds  # imported lazily to avoid a module cycle`.
The lazy import hides a real cycle. ~30 deferred in-function imports across the
package (e.g. `cutlist.py:193,845`, `estimator.py:142,457`, `service.py:226,425`)
each mark tangled inter-module coupling invisible to tooling.

**Fix:** Move the footprint math `dsl` needs into a geometry-free module so DSL
never imports geometry; treat each remaining lazy import as a coupling smell to
unwind.

### 3.6 Stringly-typed geometry dispatch on free-text references (MED)
`builder.py:106` `is_back = "rear" in ref or "back" in ref`; `builder.py:120`
`if "top" in ref:` — cut placement decided by substring search on a free-text
joinery reference, **duplicated** verbatim in `dxf.py:205-212`. Breaks on any
reference rename or coincidental substring.

**Fix:** Carry an explicit `edge`/`face` enum on the joinery op at creation; have
builder and dxf both read it.

### 3.7 Pervasive stringly-typed enum handling (MED)
`Joinery`, `SlideType`, `Grain`, `Construction` are real `StrEnum`s, yet ~15 call
sites stringify and compare against bare literals — e.g. `cutlist.py:504`
`j = str(spec.joinery).strip().lower()` then `if j in ("screw",)`;
`critic.py:282` `str(d.slide_type).lower() == "side_mount"`. A typo
(`"side_munt"`) fails silently — no checker or test catches it.

**Fix:** Compare against enum members (`spec.joinery == Joinery.SCREW`) or
centralise normalization in one `as_joinery(spec)` helper.

### 3.8 Residual private cross-module imports (MED)
`service.py:425` imports `estimator._pack_sheet_groups`; `purchasing.py:299`
imports `planning._glue_up_count`; `service.py:464` writes `po_est._rate`. Promote
these to public names — importing another module's `_private` re-couples across
the boundary the public-API refactor established.

---

## 4. Anti-patterns & code smells (HIGH/MED)

### 4.1 God functions (HIGH/MED)
- `_validate_cabinet` — **321 lines** (`validator.py:370`), the largest function
  in the repo; extract cohesive `_check_*(spec) -> list[Issue]` groups.
- `build_result` — **261 lines** (`service.py:294`); includes a 40-line offcut
  reconciliation reaching into estimator privates (4.x). Extract `_section_*`
  helpers and move the reconciliation into estimator/purchasing.
- `critique` (159) + `_critique_project` (85) duplicate the
  `if use_cad or brep: build_model...` block (`critic.py:341-371` vs `499-530`);
  `build_package_pdf` (244).

### 4.2 Silent broad-`except` clusters (MED)
Beyond the validator (1.1): `tooling.py:354-357, 432-435` (`required_operations`
→ empty tool list on any error), `planning.py:175-180, 288-291` (→ "0 parts" /
"[]"), `service.py:544, 550` (→ `[]`/`None`). Each turns an internal failure into
plausible-but-wrong empty data with no log. Contrast `builder.py:190+`, which does
this correctly with `log.warning(..., exc_info=True)`. Narrow the exception type
and log.

### 4.3 Silent value clamping hides bad input (MED)
`web.py:127-130, 139-142` (attempts/factor silently coerced), `dsl.py:796,801`
(geometry from clamped depth), `furniture_types.py:1494,1690`
(`max(0, min(int(spec.drawers), 2/3))` — a request for 5 drawers silently becomes
2 or 3). Surface a warning when clamping actually changes a user-facing value;
name the magic bounds.

### 4.4 Residual inline magic numbers (MED)
Despite the strong `constants.py`: `critic.py:259` `abs(w-b) < 0.6`,
`critic.py:288` `if lip > 3.0`, `critic.py:483` `if coverage < 60`,
`purchasing.py:331` clamp `200/2/12`. Lift into named constants.

### 4.5 Import-time side-effect registry population (LOW)
`__init__.py:28` `from . import furniture_types  # import for side effects` —
ordering-sensitive global-mutable-state init. An explicit
`register_builtin_types()` or decorator registration would be less fragile.

**Clean bills of health** (verified): no mutable default args, no bare `except:`,
no `print()` in library code, no TODO/FIXME/HACK markers, no commented-out dead
code.

---

## 5. Testing practices (HIGH/MED)

### 5.1 CAD geometry & exporters have zero CI coverage (HIGH)
CI installs only `.[render,web,dev]` — **not `[cad]`**. So **23
`pytest.importorskip("build123d")` calls across 12 files skip on every CI run**,
leaving uncovered: `builder.py` (315 LOC, the entire spec→B-Rep compiler incl. the
`joinery_geometry` dado/rabbet/bore path), `exporters.py` STEP/STL/GLB, all 6
`test_joinery_geometry.py` tests, and `critic._brep_interferences`. A refactor can
break STEP export and CI stays green.

**Fix:** Add a separate CI job (matrix entry) that installs `[cad]` and runs the
geometry/export suite — even nightly. Mark these `@pytest.mark.cad` instead of
inline `importorskip` so the gap is visible/countable.

### 5.2 Untested modules (HIGH)
6 modules have no behavioral coverage: **`furniture_types.py` (2088 LOC — the
largest module, nearly untested)**, `cli.py` (332, only `_default_unit` poked),
`sources.py` (91), `proposal.py` (158, only via gated `test_report`),
`pdf_common.py` (193, gated), `dispatch.py` (80). `validator.py` also has no
dedicated error-path suite.

**Fix:** Direct tests for `furniture_types.py` (top priority) and `cli.py`
(`subprocess` invocation); make PDF coverage not depend on optional `reportlab`.

### 5.3 Heavy fixture duplication — no `conftest.py` (MED)
A near-identical `_cab` spec builder is redefined in **15 files**; `_spec` in 4;
`base`/`base_spec` in 2. There is no shared fixture, so a `CabinetSpec` signature
change forces ~20 lockstep edits.

**Fix:** A `tests/conftest.py` with a parametrizable `cab_factory` fixture (or
`tests/factories.py`); delete the per-file copies.

### 5.4 Golden tests freeze bytes, not behavior (MED)
`test_golden.py` snapshots entire serialized output (incl. raw DXF text) per spec
and asserts byte-equality, regenerated via `WOODAI_REGEN_GOLDEN=1` (1.1 MB of
fixtures). High churn, low diagnostic value, encourages "just regen it." Pair each
spec with a handful of *named behavioral assertions*; don't snapshot raw DXF text.

### 5.5 Tests coupled to internals (MED/LOW)
`test_techdebt.py:63,90` assert object **identity** (`_pack_positions is pack`) —
a behavior-preserving refactor that wraps the function breaks the test. 8
underscore-private internals imported across 7 test files. One assertion-free
test (`test_planning.py:133`). ~120 exact-string assertions on human-readable
prose (brittle to copy-edits). Assert behavioral equivalence / codes instead.

---

## 6. Web, CLI, packaging, security (MED/LOW)

- **CI gaps (MED):** no type checking (no mypy/pyright anywhere), no coverage
  reporting, the 2.4k-line SPA is never linted, and the `anthropic`/`build123d`
  import guards never run in CI. Add a `mypy src` job, `pytest --cov` floor, and
  one `.[all]` job.
- **Ruff scope too narrow (MED):** `pyproject.toml:49-50` `select = ["F"]` misses
  bug-class rules — especially `B` (bugbear: mutable defaults, `except Exception`
  misuse), `I`, `UP`. Add `E, W, B, I, UP`.
- **Monolithic SPA (MED):** `static/index.html` is 2434 lines (HTML + CSS + 78
  inline JS functions, module-global state, 26 `innerHTML` assignments). Split
  into ES modules and unit-test the pure helpers (`esc`, `dispFromMM`).
- **`/api/design` has no auth/rate-limit (HIGH/contextual):** the cost clamp bounds
  loop depth but not request volume; anyone reaching the port can drive unbounded
  paid Claude calls. Gate behind a key/rate-limit for public deploys. (XSS, error
  leaks, and cost clamps are **handled well** — verified.)
- **CDN without SRI (MED):** `index.html:8` loads `model-viewer` from `unpkg.com`
  unversioned, no `integrity`. Pin + add SRI or vendor it.
- **CLI lacks the web layer's error handling (MED):** `cli.py:323-326` lets
  `json.loads`/`spec_from_dict` throw raw tracebacks (web returns HTTP 400 for the
  same input); `--from-stock` parses the boards file twice.
- **Doc debt (MED):** `docs/` holds 9 overlapping planning/tech-debt docs (incl.
  this one); three contain completed `✅`/`Status:` checklists masquerading as open
  work. Archive completed plans; keep one living `ROADMAP.md`. Only
  `design-principles.md` + `validation-rules.md` are load-bearing.
- **Packaging (LOW):** `pyproject` `all` group omits `ruff` (so `.[all]` can't
  lint) and isn't a superset of `dev`; all deps float `>=` with no upper cap or
  lockfile. `delete_merged_branches.sh` hardcodes 30 long-gone branch names and
  `set -e` aborts on the first already-deleted one — delete it.
- **Scattered config (LOW):** env vars (`WOODAI_*`, `CONVEX_URL`,
  `ANTHROPIC_API_KEY`) read in 3 modules with `ANTHROPIC_API_KEY` in two places;
  optional-import guards spelled 5 different ways. Centralise into `config.py` and
  one `optional.require(module, hint)` helper.

---

## Recommended order of attack

**Tier 1 — correctness (small, high-value, do first):**
1. Fix the validator silent-skip safety bug (1.1).
2. Fix the regressed `clear = 13.0` by routing through `partmath` (2.1).
3. Unify the door-panel formula in `partmath` (1.2).

**Tier 2 — guardrails (cheap leverage):**
4. Add a `[cad]` CI job + `mypy` + widen ruff to `B,I,UP` (5.1, 6).
5. Add `tests/conftest.py` factories; write a `furniture_types.py` test (5.2, 5.3).

**Tier 3 — structural (the big one):**
6. Collapse the triplicated taxonomy into one self-registering spec table (3.1) —
   this is the highest-leverage refactor and unblocks splitting the
   `furniture_types.py` god-module (3.3) and introducing `LeggedSpec` (3.4).
7. Add `drilling_ops`/`PanelRole` so the registry covers the whole pipeline (3.2).

Tiers 1–2 are independently shippable and behavior-preserving (except the two
explicit bug fixes); each should land with a drift-guard test mirroring
`test_techdebt.py`.
