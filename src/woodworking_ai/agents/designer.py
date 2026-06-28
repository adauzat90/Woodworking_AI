"""The Designer agent: natural language -> validated cabinet DSL.

Implements the execute-and-verify loop that makes agentic CAD reliable (the same
idea behind Zoo's Zookeeper and Seek-CAD): the LLM proposes a spec, we
deterministically (1) validate it and (2) build + critique the resulting
geometry, feeding any issue back so the agent repairs its own output — looping
until the design is sound or we give up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..dsl import (CabinetSpec, TableSpec, Project, Assembly, spec_from_dict,
                   DSL_SCHEMA_HINT)
from ..dsl_lint import lint_spec_dict
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
- If the request is ambiguous, make the most common professional choice.
- You MAY add ONE extra top-level key, "design_notes": a short JSON array of \
plain-string notes. Add one note for each assumption you made that the customer \
did not state, and one for each way you reinterpreted or changed the request \
because a literal reading was infeasible or contradictory — always say WHY \
(e.g. "Split a 3 m cabinet into a 4-cabinet run: one carcass that wide is not \
buildable from sheet goods"). Omit the key or use [] when you followed the \
request literally with no notable assumptions. This key is metadata about your \
decisions, not part of the furniture."""


@dataclass
class DesignResult:
    spec: CabinetSpec | TableSpec | Project | Assembly
    validation: ValidationResult
    raw_responses: list[str]
    attempts: int
    critique: CritiqueResult | None = None
    # The agent's own account of the assumptions it made and the ways it
    # reinterpreted an infeasible request — the structured "we changed what you
    # asked for, because X" signal a UI (or the CLI) can surface.
    notes: list[str] = field(default_factory=list)


def _pop_design_notes(data: object) -> list[str]:
    """Pull the agent's optional ``design_notes`` off the parsed JSON.

    Removed from *data* in place so the spec the language sees stays clean (and
    the unknown-field lint doesn't flag it). Tolerant of a string or a list.
    """
    if not isinstance(data, dict):
        return []
    raw = data.pop("design_notes", None)
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def design_from_prompt(
    prompt: str,
    *,
    max_attempts: int = 3,
    model: str | None = None,
    run_critic: bool = True,
    tooling=None,
) -> DesignResult:
    """Run the NL -> DSL design loop with validate-and-repair.

    When ``run_critic`` is set, a spec that passes validation is additionally
    built and critiqued; geometry problems are fed back for repair too. When a
    :class:`~tooling.ShopTooling` inventory is given, the agent is told to use
    only joinery the shop can make, and the same constraint is enforced in
    validation so an infeasible joint is repaired like any other problem.
    """
    system = SYSTEM_PROMPT
    if tooling is not None:
        from ..tooling import designer_constraint
        system = SYSTEM_PROMPT + "\n" + designer_constraint(tooling)
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    raw_responses: list[str] = []
    last_spec: CabinetSpec | TableSpec | Project | Assembly | None = None
    last_validation: ValidationResult | None = None
    last_critique: CritiqueResult | None = None
    last_notes: list[str] = []

    for attempt in range(1, max_attempts + 1):
        text = llm.complete(system, messages, model=model)
        raw_responses.append(text)

        try:
            data = llm.extract_json(text)
            notes = _pop_design_notes(data)   # strip metadata before parsing
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

        result = validate(spec, tooling=tooling)
        last_spec, last_validation, last_notes = spec, result, notes

        # Keys the model set that the language silently dropped (typos, guessed
        # field names). Non-fatal, but surfaced so the agent can repair them
        # rather than believing it set a value it didn't.
        lint = lint_spec_dict(data)
        lint_note = ""
        if lint:
            lint_note = (
                "\n\nThese fields were not recognized and were ignored "
                "(use the correct names or remove them):\n"
                + "\n".join(f"- {i}" for i in lint)
            )

        if result.ok:
            # Spec is sane — now verify the geometry it produces.
            crit = critique(spec) if run_critic else None
            last_critique = crit
            if (crit is None or crit.ok) and not lint:
                return DesignResult(spec, result, raw_responses, attempt, crit,
                                    notes)
            if crit is not None and not crit.ok:
                feedback = (
                    "The geometry built from this spec has problems:\n"
                    f"{crit.as_feedback()}{lint_note}\n"
                    "Return a corrected JSON object that resolves every error."
                )
            else:
                # Validates and the geometry is sound; only dropped fields remain.
                feedback = (
                    "The spec is otherwise sound, but some fields were ignored:"
                    f"{lint_note}\n"
                    "Return a corrected JSON object using the right field names."
                )
        else:
            # Valid JSON but a broken design.
            feedback = (
                "The specification has problems that must be fixed:\n"
                f"{result.as_feedback()}{lint_note}\n"
                "Return a corrected JSON object that resolves every error."
            )

        messages.append({"role": "assistant", "content": spec.to_json()})
        messages.append({"role": "user", "content": feedback})

    # Exhausted attempts; return the best we have so the caller can inspect it.
    if last_spec is None or last_validation is None:
        raise RuntimeError("Designer agent never produced a parseable spec.")
    return DesignResult(
        last_spec, last_validation, raw_responses, max_attempts, last_critique,
        last_notes,
    )
