# Roadmap — Woodworking AI (living doc)

> **This is the single living roadmap.** It folds in and supersedes the dated
> planning docs now under [`archive/`](archive/):
> `IMPLEMENTATION_PLAN.md` (the "shop product" A/B/C/D workstreams),
> `HOBBYIST_ROADMAP.md` (the H-series), `HOBBYIST_PLAN_V2.md` (the G-series),
> and the DSL trio (`DSL_REVIEW.md`, `DSL_AGENT_AUTHORING_REVIEW.md`,
> `DSL_IMPLEMENTATION_PLAN.md`). Those are kept for the detailed rationale and
> file-level task breakdowns behind each shipped item; **this file is the
> current source of truth for status.** Update it in place.
>
> For the architecture itself see [`ARCHITECTURE.md`](ARCHITECTURE.md); for
> outstanding code quality work see [`TECH_DEBT.md`](TECH_DEBT.md).

---

## Shipped (do not re-build)

The historical plans are essentially complete. Highlights, by workstream:

**Shop product (`IMPLEMENTATION_PLAN.md`, A–D — ✅ complete):**
- Machine-honest geometry in DXF nest and STEP (single cabinets *and* projects).
- Critic catches joinery-level failures (incl. a real rail-vs-back collision) and
  does a render-based visual review.
- Kitchens model appliances / voids / counter cutouts.
- Numbers snap to purchasable stock; supplier-grouped purchase order; surfaced
  design revisions; customer proposal PDF.

**Hobbyist H-series (`HOBBYIST_ROADMAP.md` — ✅ largely shipped):**
- Design-against-your-tooling: `ShopTooling` capability flags + presets,
  joint→tool feasibility with feasible-substitute suggestions, validator advisory,
  AI-designer constraint, profile persistence, web **My shop tooling** panel +
  **Tools** tab, CLI `--shop/--tools`.
- Species database, leaf-furniture refactor, shelves/boxes/benches,
  cut-from-stock, skill + time planning, finishing/glue-up depth.

**Hobbyist G-series (`HOBBYIST_PLAN_V2.md` — ✅ shipped):**
- New furniture: picture frame, knock-down bed, cutting/charcuterie board,
  nightstand, desk, workbench.
- Exploded stepwise assembly walkthrough; click-to-edit dimensions on the model;
  starter-project gallery (`templates.py`, `/api/templates`); consumables +
  sourcing in the PO (`sources.py`); responsive layout + print stylesheet.

**Buildings (✅ shipped):** a `building` / barndominium leaf
(`building.py`) that **auto-places** the primary structural frame — the main
carrying beams and the support posts beneath them — sizing the post (bay) spacing
to the safe span for the section + load (`engineering.max_beam_span`). Flows
through the same validate / cut-list / geometry / cost pipeline as the furniture
leaves; models beams + posts only (no trusses/rafters/purlins/foundation).

**DSL (`DSL_*` — ✅ acted on):** parse-time lint for unknown fields/kinds,
generated-and-guarded schema hint, `Project`/`Assembly` + `definitions`/`ref`
composition, the `ApplianceVoid` placeholder, and the verify-repair feedback path.

---

## Next / candidate work

These are open directions distilled from the archived plans and the current
tech-debt audit. None is committed; sequence by impact when picking up.

1. **Collapse the spec-type registries into one self-registering table**
   (see `TECH_DEBT.md` §3.1). Highest-leverage structural change — also unblocks
   splitting the `furniture_types.py` god-module and a shared `LeggedSpec` base.
2. **Bring the whole pipeline under the leaf registry** — drilling/estimator
   currently dispatch on cabinet-shaped panel labels (`TECH_DEBT.md` §3.2).
3. **Declarative placement in the DSL** — the structural item the DSL plan
   ordered last, on top of a uniform type model.
4. **Drag-handles for on-model dimension editing** (G2b follow-up; browser QA).
5. **Wider furniture coverage** — chairs/upholstered frames, more casework types.
6. **CI hardening** — a `[cad]` job so geometry/export tests actually run, type
   checking, coverage floor (`TECH_DEBT.md` §5.1, §6).

## Manual QA

Headless tests cover the pure-math core, cut lists, validators, geometry
envelopes, the web API, and PDF generation. The browser-rendering / real-CAD /
print-scale / paid-AI paths that a machine can't verify headlessly were tracked
in `archive/TESTING_CHECKLIST.md`; fold any still-relevant checks into a fresh
list when doing a release pass.
