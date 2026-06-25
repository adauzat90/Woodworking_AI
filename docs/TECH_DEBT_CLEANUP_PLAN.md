# Tech Debt Cleanup — Implementation Plan

> **Execution status (2026-06-25).** The epic has been executed on
> `claude/app-tech-debt-audit-vu56yw`. All phases shipped, each gated by
> `make check` (ruff + 615 tests) and a golden-output safety net; the only
> intended output change was the slide-clearance correctness fix.
>
> | Phase | Status |
> |---|---|
> | 0 Safety net (golden fixtures + `make check`) | ✅ done |
> | 1 Correctness (slide clearance, XSS, critic logging, dead code, clamps) | ✅ done |
> | 2 Unify constants | ✅ done |
> | 3 Shared dimension helpers (`partmath.py`) | ✅ done |
> | 4 IO/coupling + web hardening (a/b/c) | ✅ done |
> | 5 PDF dedup (`pdf_common.py`) | ✅ done |
> | 6 Typed dispatch (`_digits`, float sentinel) | ✅ done |
> | 7 Data-driven catalogs (profile, pulls) | ✅ done (joinery/appliance tables deferred — see note) |
> | 8 Spec dispatch (`dispatch.spec_kind`) | ✅ done |
> | 9 God-functions (service, drilling, assembly classifier) | ✅ done (`designer.design_from_prompt` deferred) |
>
> **Deliberately deferred** (low value / not safely verifiable in this
> environment): the `_housed_joint`/appliance lookup-table conversions (the
> if/elif chains are readable and a static table would add complexity given the
> per-joint `mating_thickness` dependency), and decomposing
> `designer.design_from_prompt` (needs the `anthropic` extra, which isn't
> installed, so the change can't be test-verified here).

---


> Companion to [`TECH_DEBT_AUDIT.md`](./TECH_DEBT_AUDIT.md). Sequenced into 9
> independently-shippable phases. Each phase keeps the test suite green, leaves
> `main` releasable, and is sized as one reviewable PR (the big ones note where
> to split further). Ordering is deliberate: **correctness first, the
> polymorphism refactor last**, so the final refactor lands on top of helpers
> that are already extracted and test-guarded.

## Guiding rules

- **Behavior-preserving unless a fix is explicitly a bug fix.** Every phase
  except 1.x must produce byte-identical cut lists / geometry / exports for the
  example specs. Lock this with a golden-output test (see Phase 0).
- **One concept per PR.** Don't mix a constant move with a signature change.
- **Add the drift-guard test in the same PR that removes the duplication** —
  mirror the existing `tests/test_techdebt.py` pattern so the dedup can't
  silently regress.
- **No new dependencies.**

## Dependency graph

```
Phase 0 (safety net)
   └─> Phase 1 (correctness)  ── ship immediately, no deps
   └─> Phase 2 (constants)    ─┐
   └─> Phase 3 (dim helpers)  ─┤
   └─> Phase 4 (IO/coupling)  ─┤
   └─> Phase 5 (PDF dedup)    ─┤ all independent of each other
   └─> Phase 6 (typed fields) ─┘─> Phase 7 (data-driven catalogs)
                                  └─> Phase 8 (Spec protocol)  ← capstone
   └─> Phase 9 (god-functions) ── partly absorbed by 3/4/8; finish the rest
```

Phases 2–6 can be done in parallel by different people. Phase 8 depends on 3 and
6. Phase 7 depends on 6.

---

## Phase 0 — Safety net (prerequisite, ~½ day)

**Goal:** make refactors safe to verify.

1. Add `tests/test_golden.py`: for each spec in `examples/` (and a handful of
   synthetic cabinet/table/project/assembly specs), snapshot
   `generate_cutlist(spec)`, `estimate(spec)`, `drilling_schedule(spec)`, and
   the DXF text to committed fixtures. Refactor PRs must not change these unless
   they declare a behavior change.
2. Add a `Makefile` / `noxfile` target `make check` = `ruff check && pytest`.
   Confirm CI (`.github/`) runs it.
3. Record current `pytest` pass count and coverage as the baseline in the PR.

**Verify:** `make check` green; golden fixtures committed.

---

## Phase 1 — Correctness fixes (~1 day, ship first)

These are genuine bugs; each is small and independently shippable.

| Fix | Location | Change | Test |
|---|---|---|---|
| 1.1 Slide-clearance conflict | `constants.py:17` (13.0) vs `hardware.py:76`, `validator.py:29`, `dsl.py:207` (12.7) | Pick one value (½″ = **12.7** is the documented intent) and make all four read one constant. Recompute golden fixtures — this *will* shift drawer-box widths by 0.6 mm; that's the point. | Assert `SLIDE_SIDE_CLEARANCE == SlideSpec().side_clearance == Drawer().slide_clearance` |
| 1.2 Reflected XSS | `static/index.html:595-596` (+ audit the 13 `innerHTML` sites: 788, 1168, 1237, …) | Switch all dynamic/error/notes text to `textContent`; build nodes with `createElement` where markup is needed. | Manual: paste a spec whose error contains `<img onerror>`; confirm it renders as text |
| 1.3 Critic swallows B-Rep errors | `agents/critic.py:156-159` | Catch only the disjoint/empty-solid case → `vol = 0.0`; on any other exception, append a `warning` issue ("interference check failed: …") instead of reporting clean. | Test: monkeypatch the boolean op to raise; assert a warning issue is emitted, not a pass |
| 1.4 Unbounded LLM cost | `web.py:146` (`attempts`), `web.py:169` (`factor`) | Clamp `attempts` to `1..5`, `factor` to a sane range, via the Pydantic models added in Phase 4 (until then, clamp inline). | Test: POST `attempts=9999` → coerced to max |
| 1.5 Dead code | `geometry.py:445-448` (unreachable dup); `render.py:_isometric` unused `spec`; `diffing.py:_part_rows/quote_diff` unused `prices`/`sheet`; `joinery.py:219-223` no-op `CORNER_DIAGONAL` branch; `constants.py:13 BACK_RABBET` | Delete. | Existing suite must stay green |

**Verify:** golden fixtures change *only* for 1.1, and only by the expected
0.6 mm; all else identical.

---

## Phase 2 — Unify construction constants (~1 day)

**Goal:** restore `constants.py` as the single home its docstring claims.

1. Move into `constants.py` (and import everywhere, deleting the local copies):
   - `SYSTEM_PITCH = 32.0` — replaces `drilling.py:26`, `validator.py:49`,
     `hardware.py:29 PLATE_SCREW_PITCH`, and the raw `32.0` at `drilling.py:206`.
   - Hinge-cup trio `HINGE_CUP_DIA/DEPTH/INSET = 35.0/12.5/22.5` — replaces the
     copies in `hardware.py:26-28`, `validator.py:37-39`, `drilling.py:31-33`.
   - `HOUSED_DEPTH_FRACTION`, `GROOVE_BACK_INSET` (from `joinery.py:23-24`),
     `COVERAGE_M2_PER_L` (from `finishing.py`), and the accessory default
     dimensions (overhang/thickness/filler/molding from `accessories.py`).
2. Move `25.4` / `304.8` literals in `engineering.py` and `stock.py` to import
   `MM_PER_IN` / `MM_PER_FT` from `units.py`.
3. Add `tests/test_constants_single_source.py`: a guard test asserting the
   downstream symbols are identity-equal to the `constants.py` originals
   (e.g. `hardware.PLATE_SCREW_PITCH is constants.SYSTEM_PITCH`).

**Risk:** low — pure constant re-homing. **Verify:** golden fixtures unchanged.

---

## Phase 3 — Extract shared dimension helpers (~1–2 days)

**Goal:** make the "single source of truth" claim true for dimensions, not just
placement.

Create `src/woodworking_ai/partmath.py` (no CAD dep, pure functions):

```python
def drawer_box_dims(spec, opening_w, front_height) -> tuple[float, float, float]:
    """Box (width, height, depth). One definition for geometry + cutlist."""

def door_member_dims(item_or_spec) -> DoorMembers:
    """Stile/rail/panel sizes for a 5-piece door."""
```

1. Replace the body of `geometry._drawer_box_panels` (590-621) and
   `cutlist._add_drawer_box` (397-434) to call `drawer_box_dims`. Same for
   `geometry._door_panels` (547-587) / `cutlist._add_door_parts` (437-472) →
   `door_member_dims`. The clamp discrepancy (geometry's `80.0` floor) is
   resolved by putting the clamp inside the helper.
2. Create one `category_style` table shared by `render.py` (`CATEGORY_COLORS`,
   19-32) and `drawings.py` (`_STYLE`, 180-188); add the missing `drawer_box`
   entry. Put it in a small `viewstyle.py` or in `render.py` and import into
   drawings.
3. **Drift guards:** extend `tests/test_techdebt.py::
   test_front_panels_and_parts_share_dimensions` to assert drawer-box panel dims
   == drawer-box part dims; add a test that every `category` produced by
   `panel_layout` has an entry in the shared style table.

**Risk:** medium (touches the cut list). **Verify:** golden fixtures unchanged
(the helper must reproduce current numbers exactly, modulo the Phase-1 clamp
decision).

---

## Phase 4 — Collapse IO / orchestration coupling (~2–3 days; splittable)

**Goal:** one assembly pipeline; no private-symbol reach-ins; typed web layer.

**4a — CLI through the service layer.**
- Rewrite `cli.py:_emit` / `_emit_project` (27-214, ~90% duplicate) to call
  `service.build_result()` and `service.export_bytes()`, then handle *only*
  presentation (stdout text/CSV, file writing). Merge the two functions into one
  parameterized path.
- If the CLI needs sections the service doesn't yet return, add them to
  `service.build_result` rather than recomputing in the CLI.

**4b — Promote private APIs** (kills the cross-module `_`-imports):
- `validator._joinery_feasibility` → `validator.joinery_feasibility`
- `builder._require_build123d` → `builder.require_build123d`
- `estimator._sheet_price` → `estimator.sheet_price`
- Update `critic.py:270/345/503` and `purchasing.py:30` to import the public
  names.

**4c — Web layer hardening.**
- Define Pydantic request models (`BuildRequest`, `DesignRequest`,
  `ExportRequest`, `DiffRequest`, `RoomRequest`) replacing the
  `dict[str, Any]` + `payload.get(...)` handlers (web.py:122/134/157/182/209/224).
  This also implements the Phase-1 clamps declaratively.
- Compute `_capabilities()` once at startup, not per request (41-62).
- Read + cache the SPA HTML once at startup; inject `CONVEX_URL` via a
  `/api/config` endpoint the SPA fetches, not per-request string replace.
- Replace `detail=f"...: {exc}"` (129/176/237) with a logged server-side
  exception + generic client message; narrow the broad `except Exception`.

**4d — LLM abstraction (optional, small).** Introduce an `LLMClient` protocol in
`agents/llm.py` (`complete(system, messages)`, `complete_image(...)`) with an
`AnthropicClient` impl selected by env; resolve `DEFAULT_MODEL` at call time
(currently captured at import, llm.py:16). Lets tests inject a fake.

**Risk:** medium-high (user-facing CLI + web). **Verify:** golden fixtures
unchanged; manual CLI + web smoke test; new request-model validation tests.

---

## Phase 5 — De-duplicate the PDF subsystem (~1 day)

**Goal:** one home for the shared reportlab code.

Create `src/woodworking_ai/pdf_common.py`:
- `elevation_flowable(spec, *, show_ids, colors)` — unifies
  `proposal._elevation_flowable` (35-95) and `report._drawings_flowable`
  (36-97).
- `model_image(spec, avail_w)` — unifies `proposal._model_image` (98-109) and
  `report._model_image` (148-167).
- `table_style()` / paragraph styles (`mini`, `small`) — unifies the two `tbl()`
  defs in `report.py` (272-285, 349-362) and the styles repeated across both
  files.

`report.py` and `proposal.py` import from it.

**Risk:** low-medium. **Verify:** generate both PDFs for a sample spec; visually
diff against pre-change output (page count + section presence).

---

## Phase 6 — Replace stringly-typed dispatch with structured fields (~2 days)

**Goal:** stop driving behavior off free-text labels; prerequisite for Phase 8.

1. Add an explicit `category` enum field to `Part` (set at creation in
   `cutlist`) so `_part_category` (cutlist.py:136-153) becomes a field read, not
   string-sniffing on name/material.
2. Add a `role`/`category` field to `PanelBox` consumers that currently match
   `label.startswith("Door")` (drawings.py:54-69/87/108),
   `p.label.startswith("Side")` (drilling.py:162-169).
3. Give joinery ops a structured `edge`/`orientation` enum so
   `builder._apply_joinery` (106-123) stops substring-matching `reference`.
4. Replace the `if d == 0.5` float-equality sentinel (drilling.py:35/212) with
   `None` or an explicit enum.
5. Add one helper `_trailing_index(name) -> int` (regex `(\d+)$`) and replace the
   4 hand-rolled `"".join(c for c in n if c.isdigit())` idioms
   (geometry.py:459/498/502, cutlist.py:218).
6. Hardware linking: match assembly steps on a hardware `category` field, not
   `"slide"/"hinge"/"pull" in name.lower()` (assembly_steps.py:154/250-263).

**Risk:** medium (broad but mechanical). **Verify:** golden fixtures unchanged.

---

## Phase 7 — Data-driven catalogs (~1–2 days)

**Goal:** turn if/elif catalogs into tables; unify parallel taxonomies.

1. **Joinery:** replace the three if/elif chains in `joinery.py` (`_housed_joint`
   7-way, `_table_joinery` 4-way, drawer corners 4-way) with one lookup table
   keyed by joint enum → `(tool, width, depth, note)`.
2. **Appliance metadata:** consolidate `appliances._ROUGH_IN`/`_CLEARANCES`
   (25-53) and `accessories` per-type rules (140-173) into one appliance-type
   registry near `APPLIANCE_VOID_WIDTHS` in `dsl.py`.
3. **Material/role taxonomy:** make `materials.py` the single owner; derive
   cutlist's `_CATEGORY_PREFIX`/`_CATEGORY_TO_AREA`/`_PANEL_LABEL_TO_PART`/
   `SOLID_LUMBER_MATERIALS`, stock's `STOCK_DESCRIPTIONS`, and finishing's
   `_HIDDEN`/`_BOTH_FACES` from it.
4. **`profile.py`:** drive `to_dict`/`from_dict` from `dataclasses.fields()`
   instead of the field list repeated 4× (31-38/70-82/89-103/134).
5. **`hardware._PULLS` (142-147):** collapse the 4 identical rows to one generic
   pull until real per-brand parts exist.

**Risk:** medium. **Verify:** golden fixtures unchanged.

---

## Phase 8 — The capstone: `Spec` protocol + polymorphic dispatch (~3–4 days)

**Goal:** eliminate the 12-module `isinstance(ApplianceVoid → ComponentGroup →
TableSpec → cabinet)` ladder so a new furniture type is *one class*, not 12
edits. Do this **last**, once the per-branch bodies are already small helpers.

Today the spec types (`CabinetSpec`, `TableSpec`, `ApplianceVoid`,
`ComponentGroup`/`Project`/`Assembly`) are unrelated dataclasses. Two viable
designs:

- **Option A — protocol on the spec classes.** Define a `Spec` `Protocol`/ABC
  with the pipeline operations and implement them on each dataclass:
  `layout(self) -> list[PanelBox]`, `cutlist(self) -> CutList`,
  `validate(self) -> list[Issue]`, `estimate(self)`, `drilling(self)`,
  `joinery(self)`, `assembly_plan(self)`, `bounds(self)`. Each pipeline function
  becomes `spec.layout()` etc. Keeps geometry/cutlist logic with the type.
- **Option B — dispatch registry (recommended).** Keep the logic in the existing
  modules but register handlers per type:
  ```python
  # geometry.py
  _LAYOUT = {}
  def register_layout(cls): ...        # decorator
  def panel_layout(spec): return _LAYOUT[type(spec)](spec)
  ```
  Repeat the registry pattern in cutlist, validator, estimator, drilling,
  joinery, assembly_steps, builder, render, purchasing. A new type registers its
  handlers without touching the dispatchers. This is less invasive to the
  current module boundaries than Option A and keeps the no-CAD-dependency split
  intact.

**Recommendation:** Option B — it preserves the deliberate module separation
(cutlist/validator have no CAD dep) while removing the ladders.

Migration order (one module per commit, golden fixtures green after each):
`validator` → `cutlist` → `estimator` → `drilling` → `joinery` →
`assembly_steps` → `geometry` → `builder` → `render` → `purchasing` → `critic`.

Add `tests/test_extensibility.py`: define a trivial throwaway `DemoSpec`,
register handlers, and assert it flows through `validate`/`generate_cutlist`/
`panel_layout` without editing any dispatcher — proving the ladder is gone.

As each module migrates, its god-function shrinks naturally
(`generate_cutlist` 591-798, `panel_layout` 325-443 lose their leading ladders).

**Risk:** high (touches every stage) — mitigated by per-module commits and the
golden net.

---

## Phase 9 — Finish god-function decomposition (~1 day)

Most large functions are reduced by Phases 3/4/8. Finish the stragglers:
- `service.build_result` (167-343) → per-section builder helpers (mostly done in
  4a).
- `assembly_steps._cabinet_plan` (104-273) → extract the part classifier (shares
  the Phase-6 `category` field) + step generator.
- `drilling.drilling_schedule` (148-253) → `_shelf_pin_ops` / `_slide_ops` /
  `_hinge_ops`.
- `designer.design_from_prompt` (49-116) → `_parse_attempt` /
  `_validation_feedback` / `_critique_feedback`.

**Verify:** golden fixtures unchanged.

---

## Effort summary

| Phase | Theme | Est. | Risk | Ships value |
|---|---|---|---|---|
| 0 | Safety net | ½d | — | enables the rest |
| 1 | Correctness/bugs | 1d | low | **fixes real bugs** |
| 2 | Unify constants | 1d | low | removes drift risk |
| 3 | Dimension helpers | 1–2d | med | true single-source |
| 4 | IO/coupling + web | 2–3d | med-hi | one pipeline, safer web |
| 5 | PDF dedup | 1d | low | maintainability |
| 6 | Typed dispatch | 2d | med | enables Phase 8 |
| 7 | Data-driven catalogs | 1–2d | med | extensibility |
| 8 | Spec protocol | 3–4d | high | **kills the 12× ladder** |
| 9 | God-functions | 1d | low | readability |

**Total ≈ 13–18 engineer-days.** Phases 1–2 deliver the bug fixes and the
highest-risk-per-line wins in the first ~2 days; Phase 8 is the structural
payoff and is intentionally deferred until the groundwork makes it safe.

## Definition of done

- `make check` green at every phase boundary.
- Golden fixtures change *only* where a phase declares a behavior change (Phase
  1.1 only).
- No remaining cross-module `_private` imports; `grep -rn "isinstance(.*ComponentGroup"`
  returns only the registry/`from_dict` sites; the slide-clearance / 32 mm /
  hinge-cup constants each have exactly one definition.
- New drift-guard tests exist for every dedup (`test_techdebt.py` style).
