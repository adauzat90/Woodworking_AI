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


def _part_rows(spec) -> dict[str, dict]:
    """Cut-list parts of *spec* keyed by stable part ID — the BOM for diffing."""
    from .cutlist import generate_cutlist
    rows: dict[str, dict] = {}
    for p in generate_cutlist(spec).parts:
        key = p.id or f"{p.name}|{p.length:.0f}x{p.width:.0f}x{p.thickness:.0f}"
        rows[key] = {
            "id": p.id, "name": p.name, "qty": p.qty,
            "length": round(p.length, 1), "width": round(p.width, 1),
            "thickness": p.thickness, "material": p.material,
        }
    return rows


def quote_diff(spec_a, spec_b, *, prices=None, sheet=None) -> dict:
    """"What changed since the last quote" between two specs.

    Re-runs the estimate on each spec and reports the price delta (B minus A)
    plus the parts that were added, removed, or had their quantity/size changed.
    ``prices``/``sheet`` (the shop's :class:`PriceBook`/:class:`SheetSize`) apply
    to *both* sides so the delta reflects only the design change, not pricing.
    """
    from .estimator import estimate
    est_a = estimate(spec_a, prices=prices, sheet=sheet)
    est_b = estimate(spec_b, prices=prices, sheet=sheet)
    delta = round(est_b.total - est_a.total, 2)

    rows_a = _part_rows(spec_a)
    rows_b = _part_rows(spec_b)
    added = [rows_b[k] for k in rows_b if k not in rows_a]
    removed = [rows_a[k] for k in rows_a if k not in rows_b]
    changed = []
    for k in rows_b:
        if k in rows_a and rows_a[k] != rows_b[k]:
            changed.append({"from": rows_a[k], "to": rows_b[k]})

    return {
        "currency": est_a.currency,
        "price_from": round(est_a.total, 2),
        "price_to": round(est_b.total, 2),
        "price_delta": delta,
        "parts_added": added,
        "parts_removed": removed,
        "parts_changed": changed,
    }
