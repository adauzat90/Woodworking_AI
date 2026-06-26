"""Shared spec builders for the test suite (importable, not fixtures).

Many test modules used to each define a near-identical ``_cab`` helper; when the
``CabinetSpec`` signature changed, every copy had to change in lockstep. Import
from here instead::

    from factories import cab            # or: from factories import cab as _cab

Plain functions (not pytest fixtures) so call sites stay ``cab(width=900)`` with
no test-signature churn. ``tests/`` is on ``sys.path`` under pytest's default
import mode, so ``from factories import cab`` resolves to this file.
"""

from woodworking_ai import CabinetSpec, Drawer

# The canonical small base cabinet. Only the fields the old per-file builders set
# are pinned here; everything else falls back to CabinetSpec's own defaults, so
# this is a behaviour-preserving drop-in for the simple ``_cab(**kw)`` helpers.
_CAB_DEFAULTS = dict(width=600, height=720, depth=560, doors=2, shelves=1)


def cab(**overrides) -> CabinetSpec:
    """A canonical base cabinet; pass keyword overrides to vary it."""
    return CabinetSpec(**{**_CAB_DEFAULTS, **overrides})


def cab_with_drawer(**overrides) -> CabinetSpec:
    """The canonical cabinet plus one 140mm drawer (a common test shape)."""
    return cab(**{"drawers": [Drawer(front_height=140)], **overrides})
