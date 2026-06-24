"""The Designer agent: natural language -> validated cabinet DSL.

Implements the execute-and-verify loop that makes agentic CAD reliable (the same
idea behind Zoo's Zookeeper and Seek-CAD): the LLM proposes a spec, we validate
it deterministically, and on failure we feed the issues back so the agent
repairs its own output — looping until the spec is valid or we give up.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..dsl import CabinetSpec, DSL_SCHEMA_HINT
from ..validator import validate, ValidationResult
from . import llm


SYSTEM_PROMPT = f"""You are a master cabinetmaker and CAD engineer. You convert a \
customer's plain-language request into a precise cabinet specification expressed \
ONLY as a single JSON object in the project's furniture design language.

{DSL_SCHEMA_HINT}

Output requirements:
- Respond with ONE JSON object and nothing else. No prose, no markdown fences.
- Choose sensible, buildable defaults for anything the customer did not specify.
- Convert imperial measurements to millimetres.
- If the request is ambiguous, make the most common professional choice."""


@dataclass
class DesignResult:
    spec: CabinetSpec
    validation: ValidationResult
    raw_responses: list[str]
    attempts: int


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response, tolerating fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]!r}")
    return json.loads(candidate[start : end + 1])


def design_from_prompt(
    prompt: str,
    *,
    max_attempts: int = 3,
    model: str | None = None,
) -> DesignResult:
    """Run the NL -> DSL design loop with validate-and-repair."""
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    raw_responses: list[str] = []
    last_spec: CabinetSpec | None = None
    last_validation: ValidationResult | None = None

    for attempt in range(1, max_attempts + 1):
        text = llm.complete(SYSTEM_PROMPT, messages, model=model)
        raw_responses.append(text)

        try:
            data = _extract_json(text)
            spec = CabinetSpec.from_dict(data)
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
            return DesignResult(spec, result, raw_responses, attempt)

        # Valid JSON but a broken design — feed the issues back for repair.
        messages.append({"role": "assistant", "content": spec.to_json()})
        messages.append({
            "role": "user",
            "content": (
                "The specification has problems that must be fixed:\n"
                f"{result.as_feedback()}\n"
                "Return a corrected JSON object that resolves every error."
            ),
        })

    # Exhausted attempts; return the best we have so the caller can inspect it.
    if last_spec is None or last_validation is None:
        raise RuntimeError("Designer agent never produced a parseable spec.")
    return DesignResult(last_spec, last_validation, raw_responses, max_attempts)
