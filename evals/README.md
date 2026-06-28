# Designer accuracy — measured baseline

This directory holds a **measured** run of the designer accuracy eval
(`woodworking_ai/designer_eval.py`), not just the harness. It answers the
question a skeptic asks first: *does "36 inch sink base, two shaker doors"
actually become that spec?*

## Result (2026-06-27)

| Suite | Cases | Produced by | Pass | Buildable | Intent |
|---|---|---|---|---|---|
| `default` (curated, unambiguous) | 8 | Opus-class | **8/8** | 100% | 100% |
| `adversarial` (unit traps, inferred type, missing dims, over-constrained) | 8 | Opus-class | **8/8** | 100% | 100% |
| `stress` (fractional-inch/odd-metric conversion, specific enums, per-drawer attrs, exact multiset, exclusions) | 6 | **Haiku** | **6/6** | 100% | 100% |
| `ambiguous` (no single right answer — scored on a defensible envelope) | 4 | Opus-class | **4/4** | 100% | 100% |
| `projects` (multi-cabinet runs incl. an L-shape; buildable covers placement collisions) | 3 | Opus-class | **3/3** | 100% | 100% |
| **committed total** | **29** | mixed | **29/29 (100%)** | 100% | 100% |

The `adversarial` suite was **also** run on Haiku and scored **8/8** (those
specs aren't the ones committed here). So across both model tiers, every prompt
tried — **37/37** — passed.

Full per-case detail is in [`baseline.json`](baseline.json); the specs the
designer produced are under [`specs/`](specs/).

### What this says about the failure boundary

We deliberately pushed for failures: a cheaper, weaker model (**Haiku**) and a
**strict** suite (fractional inches like `37 3/8″`, odd metric like `0.725 m`
held to ±3 mm, specific enum values, per-drawer `undermount`/`dovetail`, an exact
`{140,180,180,220}` drawer-height multiset, and a "no toe kick, no doors"
exclusion). It still scored 6/6. **The boundary was not reached** — the
structured DSL + schema hint + the validate/critique repair loop carry even a
small model. That is evidence *for* the project's core thesis (LLMs are reliable
at writing and repairing *language*, not binary geometry).

The `ambiguous` and `projects` suites (added next) closed two of those gaps:

- **Multi-cabinet projects work.** All three project prompts produced a valid
  `kind: project` with correctly placed components — including an **L-shaped run**
  whose two perpendicular runs don't collide at the inner corner (the validator's
  footprint-overlap check is part of "buildable").
- **Ambiguity is handled by a sane default, never a question.** Every ambiguous
  prompt landed inside a defensible envelope (a metre-tall request → a 1000 mm
  piece; "a nightstand" → bedside proportions). But note the **real limitation**
  this surfaces: the designer *never asks a clarifying question* — it always
  commits to one reading. The guesses here were all reasonable, but for
  high-stakes ambiguity (dimensions that actually matter) silent guessing is a UX
  risk worth a product decision.

Still genuinely untested: prompts that **should be refused or flagged as
infeasible** (e.g. a single 3-metre-wide cabinet) rather than quietly built.

A case **passes** only if the spec is *buildable* (passes the validator **and**
the geometry critic with no errors) **and** meets every *required* intent check
(the spec is what the prompt unambiguously asked for). Defaults the prompt left
open are not scored, so a miss is a real disagreement.

## How this was produced

Each prompt was handed to Claude (Opus-class) acting as the Designer agent
through the project's **real** `SYSTEM_PROMPT` + DSL schema hint, with **no
knowledge of the intent checks**. Each agent self-repaired its spec to
buildability against the validator + critic, then the spec was scored by
`designer_eval.score_spec`. This is an **API-key-free proxy** for `woodai eval`:
it exercises the same authoritative scoring, with agents standing in for the
live `design_from_prompt` agent + repair loop.

## Honest caveats

- **100% is not "solved."** It says the happy path and these adversarial traps
  are handled by a strong model with a repair loop. It does **not** characterize
  the failure boundary — that likely needs weaker/cheaper models
  (`claude-sonnet`/`claude-haiku`) or genuinely ambiguous prompts with no single
  correct answer. Run `woodai eval --suite adversarial --model claude-haiku-...`
  to push for the boundary.
- This is a **proxy**, not the live pipeline. The authoritative number comes from
  `woodai eval` (needs `ANTHROPIC_API_KEY`), which uses the actual designer.

## Refusal suite — does it flag the infeasible? (`refusal.json`)

The suites above ask "does a *reasonable* request become the right spec?" The
refusal suite asks the opposite: when a request is **infeasible or
contradictory**, does the system flag it, or silently build something physically
wrong? This is a property of the deterministic validator + critic (not the LLM),
so it is hand-built and **needs no API key** (`woodai eval --suite refusal`).

A case passes when the system meets the expected minimum severity for a
*faithful* encoding of the request; it **fails only if the system is silent**.

| Result (10 cases) | |
|---|---|
| flagged (not silently accepted) | **10/10 (100%)** |
| hard-blocked with an error | **7/10 (70%)** |
| warning only | 3/10 |

Hard errors: negative / zero / >6000 mm dimensions, >50 shelves, a drawer taller
than its opening, ten drawers that can't fit, and (via the critic) five shelves
that overlap in a 200 mm box. Warning-only: a single 3 m cabinet (a part exceeds
sheet stock), a wall cabinet with a toe kick, a 2 m-deep base.

**Nothing is silently accepted** — worst case the system warns. The one
defensible-but-debatable spot: a part larger than any standard sheet is a
*warning*, not an error, even though you literally cannot cut it from one sheet
(a shop can seam or order oversize stock, so it's a judgment call). Promoting
that to an error for sheet-good construction is a one-line severity change if you
want it hard-blocked.

### End-to-end: what the *designer* does with an infeasible prompt

Separately, three infeasible prompts were run through the live designer flow
(subagents). It does not ask a clarifying question — but it does **reinterpret
sensibly and explain**, which is better than silent compliance:

- *"a single base cabinet 3 metres wide"* → it emitted a **project of four 750 mm
  base cabinets** under one countertop, noting a 3 m carcass isn't buildable from
  sheet goods. (Recognized the infeasibility and turned it into a run.)
- *"a 400 mm base with a 600 mm drawer front"* → kept the explicit drawer and
  **grew the cabinet to 760 mm**, stating which constraint it kept and why.
- *"a wall cabinet with a toe kick"* → **omitted the toe kick**, explaining wall
  cabinets don't have one.

These resolutions used to happen silently in the spec. They are now surfaced as
a structured **`design_notes`** signal: the agent reports each assumption and
each reinterpretation (with the reason), captured on `DesignResult.notes`,
returned as `notes` from `POST /api/design`, printed by `woodai design`, and
shown in the web UI as a *"What the AI assumed or changed"* panel with an
*"N AI changes"* pill — so a silent reinterpretation (a 3 m cabinet becoming a
run) never goes unnoticed.

## Reproduce / extend

```bash
# the real thing (needs a key)
woodai eval --suite all --json evals/baseline.json

# refusal suite is deterministic — no key
woodai eval --suite refusal --json evals/refusal.json

# guard the committed fixtures in CI (no key, deterministic)
pytest tests/test_eval_baseline.py tests/test_refusal_suite.py
```

Add prompts + intent checks in
[`designer_eval.py`](../src/woodworking_ai/designer_eval.py)
(`DEFAULT_CASES` / `ADVERSARIAL_CASES` / … / `REFUSAL_CASES`).
