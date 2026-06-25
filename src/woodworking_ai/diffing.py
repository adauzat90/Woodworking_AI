"""Spec diffing: compare two furniture specs field by field.

Powers the design "compare revisions" feature — given two spec dicts (an earlier
revision and the current one), report exactly which fields changed, flattening
nested material/toe-kick/drawer structures into dotted paths. Pure data.
"""

from __future__ import annotations

from typing import Any


def spec_diff(a: Any, b: Any, prefix: str = "") -> list[dict]:
    """Field-level changes turning *a* into *b*, as ``{path, from, to}`` rows.

    Nested dicts recurse into ``parent.child`` paths; lists (e.g. drawers,
    accessories) are compared whole, since reordering is itself a change.
    """
    changes: list[dict] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            changes += spec_diff(a.get(key), b.get(key),
                                 f"{prefix}{key}" if not prefix else f"{prefix}.{key}")
        return changes
    if a != b:
        changes.append({"path": prefix, "from": a, "to": b})
    return changes


def diff_summary(changes: list[dict]) -> str:
    """One-line human summary of a diff (for a revision list)."""
    if not changes:
        return "no changes"
    head = ", ".join(c["path"] for c in changes[:3])
    more = f" +{len(changes) - 3} more" if len(changes) > 3 else ""
    return f"{len(changes)} change(s): {head}{more}"
