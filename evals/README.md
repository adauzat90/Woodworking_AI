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
| **committed total** | **22** | mixed | **22/22 (100%)** | 100% | 100% |

The `adversarial` suite was **also** run on Haiku and scored **8/8** (those
specs aren't the ones committed here). So across both model tiers, every prompt
tried — **30/30** — passed.

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

What is **not** yet tested, and where failures most likely live: genuinely
ambiguous intent with no single right answer, multi-cabinet **projects/kitchens**,
and prompts that should trigger a clarifying question or a refusal rather than a
guess. Those are the next cases to add.

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

## Reproduce / extend

```bash
# the real thing (needs a key)
woodai eval --suite all --json evals/baseline.json

# guard the committed fixtures in CI (no key, deterministic)
pytest tests/test_eval_baseline.py
```

Add prompts + intent checks in
[`designer_eval.py`](../src/woodworking_ai/designer_eval.py)
(`DEFAULT_CASES` / `ADVERSARIAL_CASES`).
