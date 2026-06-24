"""Proportion & visual-balance advisories (PROP-* rules).

Pure geometry helpers for the validator's INFO-level aesthetic checks: the
golden ratio for a piece's primary rectangle, leg slenderness, and drawer-bank
graduation. These never block a build — they nudge toward proportions the eye
reads as deliberate. See docs/design-principles.md §2.
"""

from __future__ import annotations

GOLDEN = (1.0 + 5.0 ** 0.5) / 2.0   # ≈ 1.6180

# Ratios the eye reads as intentional: square, 5:4, 4:3, 3:2, golden, 2:1.
PLEASING_RATIOS: tuple[float, ...] = (1.0, 1.25, 4.0 / 3.0, 1.5, GOLDEN, 2.0)

AWKWARD_TOL = 0.12   # distance from any pleasing ratio that reads as "off"
GOLDEN_TOL = 0.05    # within this of GOLDEN counts as already golden

# Leg cross-section as a fraction of overall height (visual heft of a table).
LEG_MIN_RATIO = 0.045   # below this the leg looks spindly/under-built
LEG_MAX_RATIO = 0.13    # above this it looks clunky/over-built

GRADUATION_TOL = 2.0    # mm slop when comparing drawer heights


def ratio_of(a: float, b: float) -> float:
    """Aspect ratio (long side / short side), always >= 1."""
    lo, hi = sorted((abs(a), abs(b)))
    return hi / lo if lo > 0 else float("inf")


def nearest_pleasing(ratio: float) -> tuple[float, float]:
    """Closest pleasing ratio and the absolute distance to it."""
    best = min(PLEASING_RATIOS, key=lambda r: abs(r - ratio))
    return best, abs(best - ratio)


def is_golden(ratio: float, tol: float = GOLDEN_TOL) -> bool:
    return abs(ratio - GOLDEN) <= tol


def is_awkward(ratio: float, tol: float = AWKWARD_TOL) -> bool:
    """True if the ratio sits far from every pleasing proportion."""
    return nearest_pleasing(ratio)[1] > tol


def golden_targets(longer: float, shorter: float) -> tuple[float, float]:
    """Two ways to reach the golden ratio for a `longer`×`shorter` rectangle:
    (longer with the short side kept, shorter with the long side kept).
    """
    return (shorter * GOLDEN, longer / GOLDEN)


def slenderness(leg: float, height: float) -> float:
    """Leg cross-section as a fraction of overall height."""
    return leg / height if height > 0 else 0.0


def is_well_graduated(heights: list[float], tol: float = GRADUATION_TOL) -> bool:
    """True if a drawer bank (ordered top->bottom) is either uniform or
    graduated (heights non-decreasing toward the bottom). Anything else —
    e.g. a tall drawer sandwiched between short ones — reads as irregular.
    """
    if len(heights) <= 1:
        return True
    uniform = max(heights) - min(heights) <= tol
    non_decreasing = all(heights[i] <= heights[i + 1] + tol
                         for i in range(len(heights) - 1))
    return uniform or non_decreasing
