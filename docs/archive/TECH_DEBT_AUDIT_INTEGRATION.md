# Tech Debt Audit — Woodworking AI (`integration` branch)

> Date: 2026-06-25 · Scope: `src/woodworking_ai/**` (~14.7k LOC, 50 modules) +
> `src/woodworking_ai/static/index.html` (1.4k lines). Method: full read of every
> module plus five parallel deep-reads, each finding **verified against the
> current code** (`file:line` quoted). Findings are graded **HIGH / MED / LOW**
> by risk × effort-to-fix.
>
> > **Remediation status (update):** every finding below has since been addressed
> on this branch. Highlights: critic now surfaces B-Rep kernel failures as a
> warning (§9); the `web.py` parse-error info leak is closed (§11); the duplicate
> `_project_cutlist` is gone — purchasing reuses `cutlist.project_hardware` (§2);
> the residual `isinstance` ladders route through `dispatch` (§3); the three
> joinery if/elif chains are lookup tables and validator compares enum members
> (§4); a `Part.category` field centralises the role heuristic (§4); the
> material-usage-label vocabulary is centralised in `materials.py` with
> drift-guard tests (§5); cross-module private imports are promoted to public
> APIs and a shared `place_rect`/`trailing_index`/`GEOMETRY_EPSILON` removed the
> copied transforms (§6, §11); an `LLMClient` protocol + `get_model()` make the
> LLM layer injectable and runtime-configurable (§8); `profile` serde moved to
> field metadata (§10); export wrappers collapsed, dead params/aliases removed,
> colours share one palette (+drawer_box), SPA HTML cached (§11); the two
> leaf-registration conventions are now documented and `_cabinet_cutlist`'s
> fronts block is extracted (§1, §7). Full suite: 827 passed, 25 skipped.

This audit targets the **`integration` branch**, which is the superset of the
> feature branches and is materially ahead of the branch the earlier
> `docs/TECH_DEBT_AUDIT.md` was written against. Several of that document's
> headline issues are **already fixed here** (see §0); this audit re-baselines on
> what is true *now* and covers the modules that document never saw
> (`furniture.py`, `furniture_types.py`, `cutplan.py`, `dsl_lint.py`,
> `planning.py`, `room.py`, `species.py`, `tooling.py`, `partmath.py`, …).

---

## 0. What the integration branch already fixed ✅

Credit where due — these were HIGH items in the prior audit and are resolved here:

| Prior issue | Status on `integration` | Evidence |
|---|---|---|
| Spec-type `isinstance` ladder re-implemented in 12 modules | **Mostly fixed** — `dispatch.spec_kind()` + a `furniture` leaf registry now back every stage | `dispatch.py:37`, `furniture.py`, `geometry.py:794`, `cutlist.py:814`, `validator.py:701`, `joinery.py:231` |
| Slide-clearance constant conflict (`13.0` vs `12.7`) | **Fixed** — single `SLIDE_SIDE_CLEARANCE = 12.7` | `constants.py:16` |
| `SYSTEM_PITCH` / hinge-cup trio triplicated | **Fixed** — centralised, imported elsewhere | `constants.py:35,39-41` |
| Drawer-box dims computed twice (geometry vs cutlist) | **Fixed** — one `drawer_box_dims()` helper both import | `partmath.py:19` |
| `report.py`/`proposal.py` copy-pasted reportlab blocks | **Mostly fixed** — shared `pdf_common.py` (`elevation_flowable`, `model_image`, table/paragraph styles) | `pdf_common.py:42-193` |
| Unbounded paid-LLM cost (`attempts`/`factor` unclamped) | **Fixed** — Pydantic request models + clamps | `web.py:109,120-138` |
| Reflected XSS via `innerHTML` | **Mostly fixed** — an `esc()` helper escapes dynamic text | `index.html:396,636-637,667,1359` |
| Private symbols imported across modules (`_joinery_feasibility`, `_require_build123d`) | **Fixed** — promoted to public `joinery_feasibility`, `require_build123d` | `validator.py`, `builder.py`, `critic.py:280,355` |

The result is a genuinely well-architected codebase. The findings below are the
*next* layer — and several are **new debt introduced by the very refactors that
fixed the old debt** (notably the two-pattern leaf registry, §1).

---

## 1. The leaf registry has two competing registration patterns (HIGH — extensibility)

`furniture.py`'s docstring states the design intent plainly:

> *"Each leaf implementation lives in its home modules (geometry/cutlist/validator/…)
> and registers its stage callables here."*

The original two leaf types follow this. **Cabinet** and **table** distribute
their five stages across the home modules that own each concern:

```
geometry.py:794     furniture.register(CABINET, panels=_cabinet_layout)
cutlist.py:814      furniture.register(CABINET, cut_parts=_cabinet_cutlist)
validator.py:701    furniture.register(CABINET, validate=_validate_cabinet)
joinery.py:231      furniture.register(CABINET, joinery_ops=_cabinet_joinery)
assembly_steps:506  furniture.register(CABINET, assembly=_cabinet_plan)
```

But the three newer types — **wall_shelf, box, bench** — register **all five
stages from a single 621-line module**, `furniture_types.py`:

```
furniture_types.py:221  furniture.register(WALL_SHELF, panels=…, cut_parts=…, validate=…, joinery_ops=…, assembly=…)
furniture_types.py:416  furniture.register(BOX, …)          # same, all five stages
furniture_types.py:614  furniture.register(BENCH, …)        # same, all five stages
```

This is **two contradictory conventions for the same abstraction**, and it has
real costs:

- **`furniture_types.py` is a new god-module** that re-implements the per-stage
  structure for three types: each type has its own `panels`, `cut_parts`,
  `validate` (with duplicated `err`/`warn` closures at `furniture_types.py:130-133,
  303-306, 514-517`), `joinery_ops`, and `assembly` — the very fan-out the
  registry was meant to eliminate.
- It **reaches into other modules' privates** to do so:
  `from .cutlist import … _resolve_part_stock` (`furniture_types.py:28`) and
  `from .assembly_steps import SubAssembly, _step` (`furniture_types.py:31`). The
  home-module pattern avoids this because each stage lives where its helpers are.
- A developer adding a 6th type has **no canonical example to copy** — cabinet
  says "edit five modules," box says "edit one." This ambiguity is itself the
  extensibility tax the registry was supposed to remove.

**Remediation.** Pick one convention and make it the rule. The cleaner target is
the *co-located* one (box-style): one module per leaf type owning all five
stages, since it keeps a type's logic in one place and makes "add a type = add a
file" literally true. Migrate cabinet/table into `furniture_types/cabinet.py` /
`table.py` (or keep them split but document the split as the standard and move
`_resolve_part_stock`/`_step` to public APIs so co-located modules don't import
privates). Either way: **one pattern, documented in `furniture.py`.**

> Note: Agent exploration flagged a *KeyError on wall_shelf/box/bench* — that is
> **not** a real bug. `furniture_types.py` is imported for its side effects at
> `__init__.py:24`, so all three types are fully registered at import.

---

## 2. Duplicated `_project_cutlist` across modules (MED → HIGH within purchasing)

Two functions share a name, signature shape, and `project.components` traversal,
but do different things — a classic drift trap:

- `cutlist.py:575` `_project_cutlist(project)` — merges **parts + hardware** into
  one tagged combined cut list.
- `purchasing.py:269` `_project_cutlist(project)` — re-walks the same components,
  calls `generate_cutlist()` again per component, and merges **hardware only**.

`purchasing.py:247` calls its *own* local copy, so it pays a second
`generate_cutlist()` pass over every component and maintains a parallel merge
contract. If the combined-cutlist semantics change (e.g. how components are
tagged), the purchasing path silently diverges.

**Remediation.** Have purchasing call `cutlist._project_cutlist()` once and
aggregate hardware from its result, or rename purchasing's to
`_project_hardware_summary` and share the component-walk. Eliminates one full
cut-list recomputation per component.

---

## 3. Residual `isinstance` ladders that bypass `dispatch` (MED — extensibility)

The dispatch refactor is ~90% complete; a few stages still hand-branch on type
instead of calling `spec_kind()` / `is_group()`, so they remain on the "edit me
when a type is added" list:

- `appliances.py:103-118` — full `ComponentGroup → ApplianceVoid → ComponentGroup
  → else` ladder. Should use `spec_kind(spec) == GROUP` / `== VOID`.
- `appliances.py:118` — `isinstance(spec, (Appliance, ApplianceVoid))`:
  `Appliance` is an accessory, never a top-level spec, so that arm is **dead**.
- `geometry.py:229` — `is_group = isinstance(comp.spec, ComponentGroup)` instead
  of the existing `dispatch.is_group(comp.spec)`.

**Remediation.** Route these through `dispatch`; drop the dead `Appliance` arm.

---

## 4. Stringly-typed dispatch is pervasive (MED — fragility)

Behaviour is repeatedly driven by substring/prefix/`.lower()` matching on
free-text labels and by re-stringifying enums — brittle to any rename and
invisible to the type checker:

- **Part role reverse-engineered from its name** — `cutlist.py:138`
  `_part_category` does `"box" in n and "drawer" in n`, `"shelf" in n`, mixed
  with `p.material in (...)` string sets.
- **Panel hand from label text** — `drilling.py:166-167`
  `p.label.startswith("Side")` and `s.label.endswith("R")`.
- **Joinery edge from reference text** — `dxf.py:205-217` `"rear" in ref or
  "back" in ref` / `"top" in ref` (a stray word like *"barking"* matches
  "back"); `builder.py` does the same for cut placement.
- **Hardware linked to steps by substring** — `assembly_steps.py:395,400,405`
  `"slide" in h.lower()`, `"hinge" in h.lower() or "plate" in h.lower()`.
- **Enum → str → lower → compare** — `validator.py:541,554-555,564` and
  `geometry.py:573,650,671,679` do `str(d.corner_joint).strip().lower() ==
  "dovetail"` even though `corner_joint` is already a `CornerJoint` enum
  (`validator.py:301` shows the correct `== BackStyle.GROOVED` form).
- **Joint dispatch via enum-string if-chain** — `joinery.py:65-82` `_housed_joint`
  does `j = str(joint).lower()` then 6 `if j == "…"` arms returning
  `(tool, width, depth, note)` tuples; `_table_joinery` (`joinery.py:178+`)
  repeats the shape. This is data, not control flow.

**Remediation.** Carry an explicit `category`/`role`/`edge` enum on `Part`,
`PanelBox`, and joinery ops *at creation time*; compare enums to enum members,
never to lowercased strings; replace the joint if-chains with a module-level
`{Joinery.DADO: (tool, …)}` lookup table (with a typed fallback).

---

## 5. Parallel taxonomies that must be hand-synced (MED)

The same "what role is this part / how does it read on a shopping list"
vocabulary is encoded in several hand-maintained tables across modules, none
derived from the others:

- `cutlist.py` — `_CATEGORY_PREFIX`, `_CATEGORY_TO_AREA`, `_PANEL_LABEL_TO_PART`
  (`cutlist.py:126-223`).
- `materials.py` — `AREA_ALIASES`, `FORM_LABELS`.
- `stock.py` — `STOCK_DESCRIPTIONS`.
- `finishing.py:147-149` — `_HIDDEN` / `_BOTH_FACES` material-tag literal sets.

Material-category *strings* (`"drawer box"`, `"back panel"`, `"door/front"`)
are hardcoded across **cutlist, estimator, stock, finishing** with no shared
enum — a single rename silently breaks finishing/stock/report alignment.

**Remediation.** Define the material/role taxonomy once (a frozen registry in
`materials.py`) holding ID prefix, stock area, display label, product hint, and
face-count per canonical category; derive the rest. Introduce a `Material`
(category) enum to replace the bare strings.

---

## 6. Cross-module private-symbol imports (MED — coupling)

Several modules reach across the package boundary into `_underscore` internals,
re-coupling things the public-API promotions in §0 were meant to decouple:

- `cutplan.py:281` — `from .dxf import _rect, _text, _layer_table`.
- `dxf.py:113` — `from .drilling import _placement_rotated`, then both modules
  re-implement the part-frame→sheet rotation transform (`drilling.py:311-314`
  vs `dxf.py:118-121`).
- `furniture_types.py:28,31` — `_resolve_part_stock` (cutlist), `_step`
  (assembly_steps) — see §1.
- `furniture.py:129` — `from .assembly_steps import … _step`.
- `cutlist.py:796` — `from .materials import resolve as _resolve_area` (public
  fn, but the rename obscures it).

**Remediation.** Promote the genuinely shared helpers to public names
(`dxf.rect/text/layer_table`, `drilling.placement_rotated`,
`cutlist.resolve_part_stock`, `assembly_steps.step`); extract **one** shared
`rotate_rect_placement()` mapping helper used by drilling and dxf.

---

## 7. God-functions (MED/LOW — testability)

| Function | ~Lines | Concern |
|---|---|---|
| `cutlist._cabinet_cutlist` | ~200 (`cutlist.py:608-809`) | frameless + face-frame + diagonal + fronts + drawers + mullions + hardware + accessories inline |
| `service.build_result` | ~200 (`service.py:290-492`) | ~15 sub-bundles (partly mitigated by the lazy `Assembly` dataclass at `service.py:176-226`) |
| `assembly_steps._cabinet_plan` | ~157 (`assembly_steps.py:262-419`) | part-classification + sub-assembly + step gen |
| `designer.design_from_prompt` | ~96 (`designer.py:50-145`) | prompt + parse + validate + lint + critique loop |

**Remediation.** Split into the per-section helpers already hinted by the
`_add_*` / `_*_panels` naming; keep the top-level function a thin orchestrator.

---

## 8. LLM layer has no abstraction (MED — testability / provider lock-in)

- `agents/llm.py:34` constructs `anthropic.Anthropic()` **at every call site**;
  there is no `LLMClient` protocol, so tests must monkey-patch the SDK class and
  a second provider can't be slotted in.
- `agents/llm.py:16` captures `DEFAULT_MODEL = os.environ.get("WOODAI_MODEL", …)`
  **at import**, so a runtime env change (or a test setting it) has no effect.

**Remediation.** Introduce a small `LLMClient` protocol with one concrete
Anthropic implementation injected into the designer/critic; read the model via a
`get_model()` function, not an import-time constant.

---

## 9. Critic still reports B-Rep kernel failures as "no collision" (MED — correctness)

`agents/critic.py:162-168` catches *any* exception from the boolean intersection,
sets `vol = 0.0`, and logs only at **DEBUG**:

```python
except Exception as exc:
    vol = 0.0
    _log.debug("B-Rep intersection of %r & %r failed: %s", …)
```

A zero volume is interpreted downstream as "no interference," i.e. a clean model.
This is better than the prior silent swallow (it logs), but a kernel failure
still degrades to a *passing* verdict instead of surfacing as a warning.

**Remediation.** On unexpected kernel errors emit a `warning` issue (so the
verdict isn't a false clean), log at WARNING, and reserve `vol = 0.0` for the
genuinely-disjoint case.

---

## 10. Data that should be data-driven (LOW/MED)

- **Joinery tool literals** — bit/depth numbers inline in `joinery.py:74,77,184,187`
  (`8.0, 30.0` dowel; `5.0, 25.0` Domino; …). Move to a `JOINERY_TOOLS` registry
  so a shop can re-tool without editing control flow. (See also §4 joint chains.)
- **Appliance metadata split three ways** — `appliances.py:25-53` (`_ROUGH_IN`,
  `_CLEARANCES`), `dsl.py` `APPLIANCE_VOID_WIDTHS`, and `accessories.py:140-182`
  counter/gap rules each encode the same appliance vocabulary. Consolidate into
  one appliance spec table.
- **`profile.py` `_NESTED`** (`profile.py:84-90`) is a hand-synced map of
  nested-field serializers that must track the dataclass; drive it from
  `field(metadata=…)` instead (contrast `tooling.py`, which uses
  `dataclasses.fields()` throughout).

---

## 11. Smaller items (LOW)

- **Near-identical export wrappers** — `exporters.py:25-44` `export_step/stl/glb`
  differ only by the build123d function name; collapse to one
  `_export(model, path, fn_name, **kw)`.
- **Dead / unused params** — `render._isometric` takes an unused `spec`;
  `diffing._part_rows`/`quote_diff` take unused `prices`/`sheet`;
  `estimator.py:493` keeps an unused `_sheet_price = sheet_price` back-compat
  alias (no callers).
- **Category→style table duplicated** — `render.py:20-32` `CATEGORY_COLORS` vs
  `drawings.py:180-188` `_STYLE`: currently the colours match but are stored
  twice and can drift; `drawer_box` is **missing** from `CATEGORY_COLORS` (falls
  to the `#bbbbbb` default). Share one table (e.g. in `pdf_common`).
- **Ad-hoc float epsilons** — `1e-6` literals at `dxf.py:71` and `drilling.py:128`;
  define one `GEOMETRY_EPSILON` in `constants.py`.
- **Residual `web.py` info leak** — `web.py:238` returns
  `detail=f"bad spec: {exc}"`, echoing internal parse state (the build/designer
  handlers correctly return generic text at `web.py:252,273`). Return a generic
  message; log the detail server-side.
- **Partly-typed request bodies** — `web.py` request models still hold
  `dict[str, Any]` for `spec`/`profile`/`prices`/`sheet` (`web.py:88-91,111-113`);
  promote `profile`/`prices`/`sheet` to Pydantic sub-models (leave `spec` loose;
  it has its own `spec_from_dict`).
- **Index-from-label idiom** — `"".join(c for c in n if c.isdigit())` recurs;
  `geometry.py:464` centralises it as `index_from_label`, but `drilling.py:213`
  and `dxf.py:101` re-roll their own. Route all through the shared helper.
- **Per-request SPA work** — `web.py` injects `CONVEX_URL` via `str.replace` on
  the cached template on every `/` request (`web.py:162-164`); compute the
  injected HTML once per `CONVEX_URL` value.

---

## Suggested sequencing

1. **Correctness (small, high-value):** make the Critic surface B-Rep kernel
   failures as warnings (§9); fix the `web.py:238` info leak (§11); drop the dead
   `Appliance` isinstance arm (§3).
2. **De-duplicate `_project_cutlist`** so purchasing reuses the combined cut list
   (§2).
3. **Unify the material/role taxonomy** into one registry + `Material` enum, and
   replace stringly-typed role/edge dispatch with enums carried on `Part`/
   `PanelBox`/joinery ops (§4, §5).
4. **Promote the remaining private cross-module imports** and extract the one
   shared rotation helper (§6); route the leftover `isinstance` ladders through
   `dispatch` (§3).
5. **The structural one:** pick a single leaf-registration convention and migrate
   both patterns onto it, splitting `furniture_types.py` accordingly (§1) — do
   this on top of §3/§6 so co-located modules no longer need private imports.
6. **Opportunistic:** LLM client protocol (§8); god-function splits (§7);
   data-drive joinery/appliance tables (§10); the LOW cleanups (§11).
