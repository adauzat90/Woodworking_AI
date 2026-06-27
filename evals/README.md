# Designer accuracy — measured baseline

This directory holds a **measured** run of the designer accuracy eval
(`woodworking_ai/designer_eval.py`), not just the harness. It answers the
question a skeptic asks first: *does "36 inch sink base, two shaker doors"
actually become that spec?*

## Result (2026-06-27)

| Suite | Cases | Pass | Buildable | Intent |
|---|---|---|---|---|
| `default` (curated, unambiguous) | 8 | **8/8 (100%)** | 100% | 100% |
| `adversarial` (unit traps, inferred type, missing dims, over-constrained) | 8 | **8/8 (100%)** | 100% | 100% |
| **all** | 16 | **16/16 (100%)** | 100% | 100% |

Full per-case detail is in [`baseline.json`](baseline.json); the specs the
designer produced are under [`specs/`](specs/).

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
