"""Parse-time lint of a *raw* furniture-spec dict, for the designer loop.

``dsl.from_dict`` deliberately drops unknown keys so the language can evolve
without breaking stored specs. That is right for *storage* but wrong for a
freshly authored spec: a typo'd field name (``"hieght"``) is silently discarded
and the default masks it, so the agent never learns it set nothing.

This module re-introduces the missing signal *without* touching the tolerant
loader. It walks the raw payload — recursing into components, definitions, runs,
nested material/toe-kick/drawers, stock, and accessories — and reports keys the
language will drop, with a "did you mean" suggestion. The designer surfaces these
as **warnings** in its repair feedback; they never hard-fail a build.

Pure data — no CAD dependency. The allowed-key sets are derived from the
dataclasses (``dataclasses.fields``) so they can't drift from the model.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from difflib import get_close_matches

from .dsl import (
    ApplianceVoid, Material, ToeKick, Drawer, KNOWN_KINDS, LEAF_SPEC_TYPES,
)

# Re-exported so callers (and Item 2's router) share one definition.
__all__ = ["LintIssue", "lint_spec_dict", "KNOWN_KINDS"]


def _fields(dc) -> frozenset[str]:
    return frozenset(f.name for f in dataclasses.fields(dc))


# Keys accepted on any spec node beyond its dataclass fields.
_COMMON_EXTRA = frozenset({"kind", "schema_version"})

# kind-or-alias -> allowed field set, derived from the loader's own leaf registry
# so it can never drift from what dsl.from_dict actually accepts (a new furniture
# type is covered automatically). Cabinet also accepts the legacy "type" key.
_SPEC_FIELDS: dict[str, frozenset[str]] = {}
for _kind, _cls, _aliases in LEAF_SPEC_TYPES:
    _allowed = _fields(_cls) | ({"type"} if _kind == "cabinet" else frozenset())
    for _k in (_kind, *_aliases):
        _SPEC_FIELDS[_k] = _allowed
_SPEC_FIELDS["void"] = _fields(ApplianceVoid)

_MATERIAL_FIELDS = _fields(Material)
_TOEKICK_FIELDS = _fields(ToeKick)
_DRAWER_FIELDS = _fields(Drawer)
_STOCK_FIELDS = frozenset({"form", "species"})

# Accessory key sets, kept in step with the typed accessories in ``accessories``.
_ACCESSORY_FIELDS: dict[str, frozenset[str]] = {
    "countertop": frozenset({"kind", "depth", "thickness", "material", "overhang"}),
    "appliance": frozenset({"kind", "type", "width", "height", "depth",
                            "cutout_w", "cutout_d", "cutout_x", "cutout_y",
                            "panel_ready"}),
    "filler": frozenset({"kind", "width", "side"}),
    "end_panel": frozenset({"kind", "side"}),
    "molding": frozenset({"kind", "type", "profile", "height"}),
}

_GROUP_FIELDS = frozenset({"name", "units", "components", "definitions", "runs",
                           "countertop"})
_COMPONENT_PLACEMENT = frozenset({"spec", "x", "y", "rotation", "label", "ref"})
_RUN_FIELDS = frozenset({"start", "angle", "gap", "items", "labels"})


@dataclass
class LintIssue:
    """A key the language will drop, located by a dotted path into the payload."""
    path: str        # e.g. "components[1].spec"
    key: str         # the offending key
    message: str

    def __str__(self) -> str:
        return self.message


def _route(node: dict) -> str:
    """The lint category of *node*, mirroring ``dsl._spec_from_dict``.

    Kind-first: a named kind (or alias) routes straight to its field set. A
    kind-less legacy spec (every stored cabinet/table predates the field) falls
    back to the cabinet/table shape heuristic."""
    kind = str(node.get("kind", "")).strip().lower()
    if kind == "appliance_void":
        return "void"
    if kind in ("assembly", "project") or "components" in node or "runs" in node:
        return "group"
    if kind in _SPEC_FIELDS:
        return kind
    # kind-less legacy spec — route by shape (legged table vs cabinet).
    if "leg" in node or "top_thickness" in node:
        return "table"
    return "cabinet"


def _loc(path: str) -> str:
    return f" at {path}" if path else ""


def _join(path: str, child: str) -> str:
    return f"{path}.{child}" if path else child


def _suggest(key: str, allowed) -> str:
    m = get_close_matches(key, sorted(allowed), n=1, cutoff=0.7)
    return f" (did you mean {m[0]!r}?)" if m else ""


def _check_keys(node: dict, allowed, path: str, issues: list[LintIssue],
                *, label: str = "field") -> None:
    for k in node:
        if k not in allowed:
            issues.append(LintIssue(
                _join(path, str(k)), str(k),
                f"ignored unknown {label} {k!r}{_loc(path)}{_suggest(k, allowed)}"))


def _spec_allowed(kind: str) -> frozenset[str]:
    if kind == "group":
        return _GROUP_FIELDS
    return _SPEC_FIELDS.get(kind, _SPEC_FIELDS["cabinet"])


def _lint_nested(node: dict, kind: str, path: str, issues: list[LintIssue]) -> None:
    """Lint the sub-dicts of a cabinet (material, toe-kick, drawers, stock, accs)."""
    if kind != "cabinet":
        return
    mat = node.get("material")
    if isinstance(mat, dict):
        _check_keys(mat, _MATERIAL_FIELDS, _join(path, "material"), issues)
    tk = node.get("toe_kick")
    if isinstance(tk, dict):
        _check_keys(tk, _TOEKICK_FIELDS, _join(path, "toe_kick"), issues)
    drawers = node.get("drawers")
    if isinstance(drawers, list):     # a cabinet's drawers are dicts; legged = int
        for i, dr in enumerate(drawers):
            if isinstance(dr, dict):
                _check_keys(dr, _DRAWER_FIELDS, _join(path, f"drawers[{i}]"), issues)
    stock = node.get("stock")
    if isinstance(stock, dict):
        for area, v in stock.items():
            if isinstance(v, dict):
                _check_keys(v, _STOCK_FIELDS, _join(path, f"stock.{area}"), issues)
    for i, a in enumerate(node.get("accessories", []) or []):
        if not isinstance(a, dict):
            continue
        ak = str(a.get("kind", "")).strip().lower()
        loc = _join(path, f"accessories[{i}]")
        allowed = _ACCESSORY_FIELDS.get(ak)
        if allowed is None:
            issues.append(LintIssue(
                _join(loc, "kind"), "kind",
                f"unknown accessory kind {ak!r}{_loc(loc)}"))
        else:
            _check_keys(a, allowed, loc, issues, label="accessory field")


def _lint_group(node: dict, path: str, issues: list[LintIssue]) -> None:
    _check_keys(node, _GROUP_FIELDS | _COMMON_EXTRA, path, issues)
    defs = node.get("definitions")
    if isinstance(defs, dict):
        for name, d in defs.items():
            if isinstance(d, dict):
                _lint_node(d, _join(path, f"definitions.{name}"), issues)
    for i, c in enumerate(node.get("components", []) or []):
        if isinstance(c, dict):
            _lint_component(c, _join(path, f"components[{i}]"), issues)
    for i, r in enumerate(node.get("runs", []) or []):
        if not isinstance(r, dict):
            continue
        rloc = _join(path, f"runs[{i}]")
        _check_keys(r, _RUN_FIELDS, rloc, issues)
        for j, c in enumerate(r.get("items", []) or []):
            if isinstance(c, dict):
                _lint_component(c, _join(rloc, f"items[{j}]"), issues)


def _lint_component(c: dict, path: str, issues: list[LintIssue]) -> None:
    spec = c.get("spec")
    if isinstance(spec, dict):
        _check_keys(c, _COMPONENT_PLACEMENT | _COMMON_EXTRA, path, issues)
        _lint_node(spec, _join(path, "spec"), issues)
        return
    if str(c.get("ref", "") or ""):
        _check_keys(c, _COMPONENT_PLACEMENT | _COMMON_EXTRA, path, issues)
        return
    # Inline spec: placement keys are mixed in with the spec's own fields.
    kind = _route(c)
    if kind == "group":
        _check_keys(c, _GROUP_FIELDS | _COMPONENT_PLACEMENT | _COMMON_EXTRA,
                    path, issues)
        # Recurse into the inline group's children (skip the placement keys).
        for i, child in enumerate(c.get("components", []) or []):
            if isinstance(child, dict):
                _lint_component(child, _join(path, f"components[{i}]"), issues)
        return
    allowed = _spec_allowed(kind) | _COMPONENT_PLACEMENT | _COMMON_EXTRA
    _check_keys(c, allowed, path, issues)
    _lint_nested(c, kind, path, issues)


def _lint_node(node: dict, path: str, issues: list[LintIssue]) -> None:
    kind = _route(node)
    if kind == "group":
        _lint_group(node, path, issues)
        return
    if kind == "void":
        _check_keys(node, _SPEC_FIELDS["void"] | _COMMON_EXTRA, path, issues)
        return
    _check_keys(node, _spec_allowed(kind) | _COMMON_EXTRA, path, issues)
    _lint_nested(node, kind, path, issues)


def lint_spec_dict(raw) -> list[LintIssue]:
    """Return the keys *raw* carries that the language will silently drop.

    Recurses through groups, components, definitions, runs, and the nested
    cabinet sub-dicts. Returns ``[]`` for a clean payload. Never raises — a
    malformed payload simply yields whatever issues it can find.
    """
    issues: list[LintIssue] = []
    if isinstance(raw, dict):
        _lint_node(raw, "", issues)
    return issues
