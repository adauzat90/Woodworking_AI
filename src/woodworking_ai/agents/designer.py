"""The Designer agent: natural language -> validated cabinet DSL.

Implements the execute-and-verify loop that makes agentic CAD reliable (the same
idea behind Zoo's Zookeeper and Seek-CAD): the LLM proposes a spec, we
deterministically (1) validate it and (2) build + critique the resulting
geometry, feeding any issue back so the agent repairs its own output — looping
until the design is sound or we give up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..dsl import (CabinetSpec, TableSpec, Project, Assembly, spec_from_dict,
                   DSL_SCHEMA_HINT)
from ..validator import validate, ValidationResult
from .critic import critique, CritiqueResult
from . import llm


SYSTEM_PROMPT = f"""You are a master cabinetmaker and CAD engineer. You convert a \
customer's plain-language request into a precise furniture specification expressed \
ONLY as a single JSON object in the project's furniture design language.

The request may call for a single cabinet (casework) or a table, or a multi-part \
PROJECT (a run of cabinets / a built-in) — choose the matching spec below. For a \
table set "kind": "table"; for anything with more than one piece emit a project \
with placed components, and factor any repeated group into a reusable assembly.

{DSL_SCHEMA_HINT}

Output requirements:
- Respond with ONE JSON object and nothing else. No prose, no markdown fences.
- Choose sensible, buildable defaults for anything the customer did not specify.
- Give dimensions in millimetres, or set "units": "in" and use inches.
- If the request is ambiguous, make the most common professional choice."""


@dataclass
class DesignResult:
    spec: CabinetSpec | TableSpec | Project | Assembly
    validation: ValidationResult
    raw_responses: list[str]
    attempts: int
    critique: CritiqueResult | None = None


def design_from_prompt(
    prompt: str,
    *,
    max_attempts: int = 3,
    model: str | None = None,
    run_critic: bool = True,
) -> DesignResult:
    """Run the NL -> DSL design loop with validate-and-repair.

    When ``run_critic`` is set, a spec that passes validation is additionally
    built and critiqued; geometry problems are fed back for repair too.
    """
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    raw_responses: list[str] = []
    last_spec: CabinetSpec | TableSpec | Project | Assembly | None = None
    last_validation: ValidationResult | None = None
    last_critique: CritiqueResult | None = None

    for attempt in range(1, max_attempts + 1):
        text = llm.complete(SYSTEM_PROMPT, messages, model=model)
        raw_responses.append(text)

        try:
            data = llm.extract_json(text)
            spec = spec_from_dict(data)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            # Couldn't even parse — ask the agent to fix its output format.
            messages.append({"role": "assistant", "content": text})
            messages.append({
                "role": "user",
                "content": (
                    f"That could not be parsed as the spec JSON ({exc}). "
                    "Respond with exactly one valid JSON object and nothing else."
                ),
            })
            continue

        result = validate(spec)
        last_spec, last_validation = spec, result

        if result.ok:
            # Spec is sane — now verify the geometry it produces.
            crit = critique(spec) if run_critic else None
            last_critique = crit
            if crit is None or crit.ok:
                return DesignResult(spec, result, raw_responses, attempt, crit)
            feedback = (
                "The geometry built from this spec has problems:\n"
                f"{crit.as_feedback()}\n"
                "Return a corrected JSON object that resolves every error."
            )
        else:
            # Valid JSON but a broken design.
            feedback = (
                "The specification has problems that must be fixed:\n"
                f"{result.as_feedback()}\n"
                "Return a corrected JSON object that resolves every error."
            )

        messages.append({"role": "assistant", "content": spec.to_json()})
        messages.append({"role": "user", "content": feedback})

    # Exhausted attempts; return the best we have so the caller can inspect it.
    if last_spec is None or last_validation is None:
        raise RuntimeError("Designer agent never produced a parseable spec.")
    return DesignResult(
        last_spec, last_validation, raw_responses, max_attempts, last_critique
    )
