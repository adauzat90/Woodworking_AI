"""Single definition of the pipeline's spec-type dispatch.

Every stage — validator, cut list, estimator, drilling, joinery, geometry,
assembly steps, … — used to re-implement the *same* ``isinstance`` ladder to
decide what kind of spec it was handed:

    if isinstance(spec, ApplianceVoid): ...
    elif isinstance(spec, ComponentGroup): ...   # Project / Assembly
    elif isinstance(spec, TableSpec): ...
    else:  # a cabinet

That ladder is the codebase's biggest extensibility tax: adding a furniture
type meant finding and editing a dozen copies in lockstep. It now lives here,
so the type taxonomy is defined once and each stage dispatches on the result.

Pure data — no CAD dependency.
"""

from __future__ import annotations

from .dsl import ApplianceVoid, ComponentGroup, LEAF_SPEC_TYPES

# Canonical pipeline kinds. For every leaf type the category string *is* its
# taxonomy kind (``TABLE == "table"``), so these are exported straight from the
# one registry in :mod:`dsl` — they can't drift from what the loader accepts.
# ``VOID`` (an ApplianceVoid placeholder) and ``GROUP`` (a Project/Assembly
# ComponentGroup) are the two non-leaf categories; ``CABINET`` is the default.
VOID = "void"
GROUP = "group"

# Bind each leaf kind as a module constant (TABLE, BOX, …) for callers that
# import them by name, and build the type→kind map spec_kind dispatches on.
_KIND_BY_CLASS: dict[type, str] = {}
for _kind, _cls, _aliases in LEAF_SPEC_TYPES:
    globals()[_kind.upper()] = _kind
    _KIND_BY_CLASS[_cls] = _kind
del _kind, _cls, _aliases

# CABINET is the default leaf and must exist even though it is also a row above.
CABINET = "cabinet"


def spec_kind(spec) -> str:
    """The pipeline category of *spec*.

    An ``ApplianceVoid`` is a leaf placeholder and a ``ComponentGroup``
    aggregates components (both need an ``isinstance`` test — the latter has
    subclasses); every other spec maps by its exact type through the one
    taxonomy, defaulting to a cabinet.
    """
    if isinstance(spec, ApplianceVoid):
        return VOID
    if isinstance(spec, ComponentGroup):
        return GROUP
    return _KIND_BY_CLASS.get(type(spec), CABINET)


def is_group(spec) -> bool:
    """True for a Project/Assembly (any :class:`ComponentGroup`)."""
    return isinstance(spec, ComponentGroup)
