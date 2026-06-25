"""Shared sheet-nesting: a next-fit-decreasing-height shelf packer.

Both the estimator (sheet *count* + utilization) and the DXF cut-layout export
(panel *positions*) need the same nesting. Keeping one packer here means the
quote and the nest diagram can never disagree about how many sheets a job takes.

A true optimal 2D bin-pack is NP-hard; shops use shelf heuristics like this too.

**Grain.** A veneered or melamine sheet has a grain direction (run along the
sheet *length*). A part whose face grain must run a fixed way therefore cannot
be freely rotated when nested — so each item carries a ``grain`` token:

* ``"length"`` — grain runs along the part's ``length``; placed length-along-
  the-sheet, never rotated.
* ``"width"``  — grain runs along the part's ``width``; rotated once so that
  axis runs along the sheet, then locked.
* ``"none"`` / ``""`` — isotropic (MDF, particleboard, hidden parts); free to
  rotate longest-side-along-length for the best yield (the original behaviour).

Locking grain can raise the sheet count — that is correct: a free pack that
rotates a veneered gable would cross the grain on a visible face.

**Sequence.** Items sharing a non-empty ``seq`` group (e.g. the door fronts of
one run) are kept contiguous and in input order so they can be cut from one
sheet in sequence for a grain/colour match, instead of being scattered by the
height sort.

Each item is ``(length, width, label)``, optionally extended with ``grain`` and
``seq``: ``(length, width, label[, grain[, seq]])``. A ``sheet`` is any object
exposing ``length``, ``width`` and ``kerf``.
"""

from __future__ import annotations

from typing import Any

# (x, y, length, width, label) of one placed panel on a sheet.
Placement = tuple[float, float, float, float, str]

# Grain tokens that pin a part's orientation when nesting.
_LOCKED_GRAINS = ("length", "width")


def orient(length: float, width: float) -> tuple[float, float]:
    """Longest side along the sheet length."""
    return (max(length, width), min(length, width))


def _oriented(length: float, width: float, grain: str) -> tuple[float, float, bool]:
    """Return ``(along_length, along_width, locked)`` honouring *grain*.

    ``locked`` is True when grain pins the orientation (no free rotation).
    """
    g = (grain or "none").strip().lower()
    if g == "length":
        return (length, width, True)
    if g == "width":
        return (width, length, True)
    return (*orient(length, width), False)


def _normalize(item: tuple) -> tuple[float, float, str, str, str]:
    """Pad an item tuple to ``(length, width, label, grain, seq)``."""
    length, width, label = item[0], item[1], item[2]
    grain = item[3] if len(item) > 3 else "none"
    seq = item[4] if len(item) > 4 else ""
    return (length, width, label, grain, seq)


class _Bin:
    """A lightweight nesting target with ``length``/``width``/``kerf``.

    The shelf packer reads only those three attributes off a sheet, so a single
    owned board (or any arbitrary rectangle) can stand in for a standard sheet.
    """

    __slots__ = ("length", "width", "kerf")

    def __init__(self, length: float, width: float, kerf: float = 0.0):
        self.length = float(length)
        self.width = float(width)
        self.kerf = float(kerf)


def pack_into_bin(items: list[tuple], length: float, width: float,
                  kerf: float = 0.0
                  ) -> tuple[list[Placement], list[str], list[str]]:
    """Shelf-pack *items* into ONE bin of ``length`` x ``width``.

    This generalises :func:`pack` to an arbitrary single bin (e.g. a board the
    shop already owns) instead of an unbounded run of identical sheets. Items
    are placed greedily, grain-aware, until the bin is full; whatever does not
    fit is returned rather than spilling onto a second bin.

    Returns ``(placed, leftover, oversize)``:

    * ``placed`` — :data:`Placement` tuples on this one bin.
    * ``leftover`` — labels of items that fit a bin this size in principle but
      ran out of room on *this* bin (a shop would cut these from another board).
    * ``oversize`` — labels of items too big for a bin this size in any allowed
      orientation (grain-respecting); they can never fit this board.

    The orientation/grain/sequence rules are identical to :func:`pack`, so a
    board layout and a sheet layout choose the same rotation for a given part.
    """
    bin_ = _Bin(length, width, kerf)
    norm = [_normalize(it) for it in items]
    oriented = [(*_oriented(l, w, grain), label, seq)
                for (l, w, label, grain, seq) in norm]
    oversize = [lbl for (l, w, _lock, lbl, _seq) in oriented
                if l > bin_.length + 1e-9 or w > bin_.width + 1e-9]
    fit = [(l, w, lbl, seq) for (l, w, _lock, lbl, seq) in oriented
           if l <= bin_.length + 1e-9 and w <= bin_.width + 1e-9]

    seq_items = [r for r in fit if r[3]]
    free_items = [r for r in fit if not r[3]]
    free_items.sort(key=lambda r: r[1], reverse=True)
    ordered = seq_items + free_items

    placed: list[Placement] = []
    leftover: list[str] = []
    shelf_y = shelf_h = cursor_x = 0.0
    for (l, w, label, _seq) in ordered:
        if cursor_x + l > bin_.length + 1e-9:      # start a new shelf
            new_y = shelf_y + shelf_h + bin_.kerf
            if new_y + w > bin_.width + 1e-9:      # ...no room: cannot place here
                leftover.append(label)
                continue
            shelf_y, shelf_h, cursor_x = new_y, 0.0, 0.0
        if shelf_y + w > bin_.width + 1e-9:        # first item already too tall
            leftover.append(label)
            continue
        placed.append((cursor_x, shelf_y, l, w, label))
        cursor_x += l + bin_.kerf
        shelf_h = max(shelf_h, w)
    return (placed, leftover, oversize)


def pack(items: list[tuple], sheet: Any
         ) -> tuple[list[list[Placement]], list[str]]:
    """Shelf-pack *items* onto *sheet*.

    Returns ``(sheets, oversize)`` where ``sheets`` is a list of sheets, each a
    list of :data:`Placement` tuples, and ``oversize`` is the labels of items
    too big to fit any single sheet (they are not placed).
    """
    norm = [_normalize(it) for it in items]
    oriented = [(*_oriented(length, width, grain), label, seq)
                for (length, width, label, grain, seq) in norm]
    # (along_length, along_width, locked, label, seq)
    oversize = [lbl for (l, w, _lock, lbl, _seq) in oriented
                if l > sheet.length or w > sheet.width]
    fit = [(l, w, lbl, seq) for (l, w, _lock, lbl, seq) in oriented
           if l <= sheet.length and w <= sheet.width]
    if not fit:
        return ([], oversize)

    # Sequence-grouped items keep their input order (for a grain/colour match);
    # everything else is packed tallest-shelf-first, which packs cleaner.
    seq_items = [r for r in fit if r[3]]
    free_items = [r for r in fit if not r[3]]
    free_items.sort(key=lambda r: r[1], reverse=True)
    ordered = seq_items + free_items

    sheets: list[list[Placement]] = [[]]
    shelf_y = shelf_h = cursor_x = 0.0
    for (l, w, label, _seq) in ordered:
        if cursor_x + l > sheet.length:           # start a new shelf
            shelf_y += shelf_h + sheet.kerf
            shelf_h = 0.0
            cursor_x = 0.0
            if shelf_y + w > sheet.width:         # ...which spills to a new sheet
                sheets.append([])
                shelf_y = 0.0
        sheets[-1].append((cursor_x, shelf_y, l, w, label))
        cursor_x += l + sheet.kerf
        shelf_h = max(shelf_h, w)
    return (sheets, oversize)
