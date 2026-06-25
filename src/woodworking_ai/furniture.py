"""Leaf-furniture registry: the per-type plug-in behind every pipeline stage.

A *leaf* is a single buildable piece of furniture (a cabinet, a table, a wall
shelf, a box) — as opposed to a :class:`~dsl.ComponentGroup` (Project/Assembly)
that aggregates leaves, or an :class:`~dsl.ApplianceVoid` placeholder.

Before this module, every stage (``geometry.panel_layout``,
``cutlist.generate_cutlist``, ``validator``, ``joinery.joinery_schedule``,
``assembly_steps.assembly_plan``) hand-coded a branch *per leaf type*. Adding a
fifth type meant editing them all in lockstep. Now a leaf type provides one
:class:`LeafFurniture` implementation and registers it under its
:mod:`dispatch` kind; each stage is a thin dispatcher that looks the leaf up and
calls the matching method. New types add no stage edits — they only register.

A :class:`LeafFurniture` provides:

* ``panels(spec)``      → ``list[PanelBox]`` — placement (single source of truth,
  shared by the builder and the Critic; never add a second placement path).
* ``cut_parts(spec)``   → ``CutList``       — the parts + hardware a shop buys.
* ``validate(spec)``    → ``list[Issue]``   — sanity checks (no CAD dependency).
* ``joinery_ops(spec, cl)`` → ``list[JoineryOp]`` — machining setup ops.
* ``assembly(spec, cl)``    → ``list[SubAssembly]`` — build plan (optional;
  defaults to a single generic "Build" sub-assembly when not provided).

Each leaf implementation lives in its home modules (geometry/cutlist/validator/…)
and registers its stage callables here, so the behaviour-preserving H0 refactor
moved *no* arithmetic — it only routed the existing branch bodies through this
table. Pure data; no CAD dependency.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class LeafFurniture(Protocol):
    """The behaviour a single buildable furniture type must provide.

    Each method is pure (no CAD dependency) and deterministic. ``cut_parts`` is
    the hub: ``joinery_ops`` and ``assembly`` receive the already-built cut list
    so part IDs line up across every output.
    """

    def panels(self, spec) -> list: ...
    def cut_parts(self, spec): ...
    def validate(self, spec) -> list: ...
    def joinery_ops(self, spec, cl) -> list: ...
    def assembly(self, spec, cl) -> list: ...


# A leaf's behaviour is registered as a bundle of stage callables. Each home
# module fills in the stages it owns (geometry → panels, cutlist → cut_parts,
# …), so no single module has to import every other. ``leaf_for`` then exposes
# the merged bundle through the LeafFurniture method surface.
_REGISTRY: dict[str, dict[str, Callable]] = {}

# The five stage hooks a leaf may register.
_STAGES = ("panels", "cut_parts", "validate", "joinery_ops", "assembly")


class _LeafView:
    """A LeafFurniture facade over a kind's registered stage callables."""

    __slots__ = ("kind", "_stages")

    def __init__(self, kind: str, stages: dict[str, Callable]) -> None:
        self.kind = kind
        self._stages = stages

    def panels(self, spec) -> list:
        return self._stages["panels"](spec)

    def cut_parts(self, spec):
        return self._stages["cut_parts"](spec)

    def validate(self, spec) -> list:
        return self._stages["validate"](spec)

    def joinery_ops(self, spec, cl) -> list:
        return self._stages["joinery_ops"](spec, cl)

    def assembly(self, spec, cl) -> list:
        fn = self._stages.get("assembly")
        if fn is not None:
            return fn(spec, cl)
        return _default_assembly(spec, cl)


def register(kind: str, **stages: Callable) -> None:
    """Register (or extend) the leaf *kind* with one or more stage callables.

    Called once per home module — e.g. ``register("table", panels=_table_layout)``
    in geometry, ``register("table", cut_parts=_table_cutlist)`` in cutlist —
    so a kind's behaviour is assembled across the modules that own each stage.
    Unknown stage names are rejected so a typo can't silently no-op.
    """
    bad = set(stages) - set(_STAGES)
    if bad:
        raise ValueError(f"unknown leaf stage(s) {sorted(bad)} for {kind!r}")
    _REGISTRY.setdefault(kind, {}).update(stages)


def get(kind: str) -> LeafFurniture:
    """The leaf implementation registered for *kind* (KeyError if missing)."""
    return _LeafView(kind, _REGISTRY[kind])


def is_registered(kind: str) -> bool:
    return kind in _REGISTRY


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def leaf_for(spec) -> LeafFurniture:
    """The leaf implementation for *spec*, via :func:`dispatch.spec_kind`."""
    from .dispatch import spec_kind
    return get(spec_kind(spec))


def _default_assembly(spec, cl) -> list:
    """A minimal one-unit build plan for a leaf that registers no ``assembly``.

    Keeps the assembly stage working for new leaf types without forcing each to
    author a bespoke plan. Imports the assembly types lazily to dodge a cycle.
    """
    from .assembly_steps import SubAssembly, _step
    parts = getattr(cl, "parts", [])
    ids = [p.id for p in parts if getattr(p, "id", "")]
    sub = SubAssembly(
        "Build", "Mill, join, assemble and finish the piece",
        part_ids=ids, category="carcass")
    sub.steps = [
        _step(1, "Mill & label all parts",
              "Cut every part to the cut-list sizes and label each with its ID.",
              ids, category="prep"),
        _step(2, "Join & assemble",
              "Cut the joinery, dry-fit, then glue and clamp square.", ids,
              category="carcass"),
        _step(3, "Sand & finish",
              "Final-sand, ease the edges, and apply the finish.",
              category="finish"),
    ]
    return [sub]
