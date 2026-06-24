"""Shared sheet-nesting: a next-fit-decreasing-height shelf packer.

Both the estimator (sheet *count* + utilization) and the DXF cut-layout export
(panel *positions*) need the same nesting. Keeping one packer here means the
quote and the nest diagram can never disagree about how many sheets a job takes.

A true optimal 2D bin-pack is NP-hard; shops use shelf heuristics like this too.
Each item is ``(length, width, label)`` and is auto-oriented longest-side-along
the sheet length. A ``sheet`` is any object exposing ``length``, ``width`` and
``kerf`` (e.g. :class:`woodworking_ai.estimator.SheetSize`).
"""

from __future__ import annotations

from typing import Any

# (x, y, length, width, label) of one placed panel on a sheet.
Placement = tuple[float, float, float, float, str]


def orient(length: float, width: float) -> tuple[float, float]:
    """Longest side along the sheet length."""
    return (max(length, width), min(length, width))


def pack(items: list[tuple[float, float, str]], sheet: Any
         ) -> tuple[list[list[Placement]], list[str]]:
    """Shelf-pack *items* onto *sheet*.

    Returns ``(sheets, oversize)`` where ``sheets`` is a list of sheets, each a
    list of :data:`Placement` tuples, and ``oversize`` is the labels of items
    too big to fit any single sheet (they are not placed).
    """
    oriented = [(*orient(l, w), label) for (l, w, label) in items]
    oversize = [n for (l, w, n) in oriented
                if l > sheet.length or w > sheet.width]
    fit = [(l, w, n) for (l, w, n) in oriented
           if l <= sheet.length and w <= sheet.width]
    if not fit:
        return ([], oversize)

    # Tallest shelves first packs cleaner.
    fit.sort(key=lambda r: r[1], reverse=True)

    sheets: list[list[Placement]] = [[]]
    shelf_y = shelf_h = cursor_x = 0.0
    for (l, w, label) in fit:
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
