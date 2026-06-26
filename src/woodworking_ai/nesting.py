"""Sheet-nesting layout for the web UI's visual cut diagram.

The cost estimate already packs every panel onto standard sheets to count how
many to buy (:func:`woodworking_ai.estimator.pack_sheets`). This module returns
the *placements* of that same pack — one labelled rectangle per part instance,
grouped by the stock it is cut from — so the front end can draw a to-scale
nesting diagram that always agrees with the quote.

It reuses :func:`woodworking_ai.packing.pack` (shared with the DXF cut-layout)
and groups parts by ``stock_key`` exactly as the estimator does, so the sheet
counts here match the Cost and Lumber tabs.
"""

from __future__ import annotations

from typing import Any

from .cutlist import CutList, generate_cutlist
from .estimator import SheetSize
from .materials import MAT_DOOR_FRONT
from .dispatch import GROUP, spec_kind
from .packing import pack


def nest_layout(spec, *, sheet: SheetSize | None = None,
                cutlist: CutList | None = None,
                combine_sheet_stock: bool = False) -> list[dict[str, Any]]:
    """Per-stock nesting placements for *spec*.

    Returns a list of stock groups, each::

        {
          "stock": "plywood",         # display name of the stock
          "thickness": 18.0,
          "sheet_length": 2440.0, "sheet_width": 1220.0,
          "sheet_count": 2,
          "utilization": 0.49,         # packed area / bought area (0..1)
          "oversize": ["B1 Back"],     # parts too big for one sheet (if any)
          "sheets": [                   # one entry per physical sheet
            [ {"x":0,"y":0,"w":560,"h":620,"label":"A1 Side"}, ... ],
            ...
          ],
        }

    Mirrors the estimator so the diagram and the quote always agree: a project
    nests **per component** by default (each cabinet cut from its own sheets) and
    **run-wide** when ``combine_sheet_stock`` pools the whole order onto shared
    sheets. Solid lumber is excluded (bought by the board foot, not as sheets).
    """
    sheet = sheet or SheetSize()

    # A project quoted per component (combine off) nests each cabinet on its own
    # sheets — so sum the per-component layouts, exactly as the estimate does.
    # (A passed combined cutlist can't express per-component packing, so dispatch
    # on the spec, not on whether a cutlist was handed in.)
    if spec_kind(spec) == GROUP and not combine_sheet_stock:
        out: list[dict[str, Any]] = []
        for comp in spec.components:
            out.extend(nest_layout(comp.spec, sheet=sheet,
                                   combine_sheet_stock=False))
        return out

    cl = cutlist or generate_cutlist(spec)
    return nest_parts(cl.parts, sheet=sheet,
                      combine_sheet_stock=combine_sheet_stock)


def nest_parts(parts, *, sheet: SheetSize | None = None,
               combine_sheet_stock: bool = False) -> list[dict[str, Any]]:
    """Nest an explicit list of cut-list :class:`Part` onto sheets.

    The leaf of :func:`nest_layout`; also used to nest a *reduced* part list
    (e.g. only the parts left to buy after cutting some from owned offcuts), so
    the diagram of "what to buy" matches the net quote.
    """
    sheet = sheet or SheetSize()

    # Group sheet-good parts by the same key the estimator buys stock by, and
    # build one labelled item per part instance (id + name, like the DXF nest).
    groups: dict[tuple, dict[str, Any]] = {}
    for p in parts:
        if p.is_solid_lumber:
            continue
        # Match the estimator: combine nests all same-thickness sheet parts.
        key = (("", "", "", p.thickness) if combine_sheet_stock else p.stock_key)
        g = groups.setdefault(key, {
            "stock": ("sheet goods" if combine_sheet_stock else p.stock_label),
            "thickness": p.thickness, "items": []})
        seq = "front" if p.material == MAT_DOOR_FRONT else ""
        code = f"{p.id} " if p.id else ""
        for i in range(p.qty):
            label = (f"{code}{p.name}" if p.qty == 1
                     else f"{code}{p.name} #{i + 1}")
            g["items"].append((p.length, p.width, label, p.grain, seq))

    out: list[dict[str, Any]] = []
    for key in sorted(groups):
        g = groups[key]
        placed_sheets, oversize = pack(g["items"], sheet)
        sheets = [
            [{"x": x, "y": y, "w": w, "h": h, "label": label}
             for (x, y, w, h, label) in ps]
            for ps in placed_sheets
        ]
        used = sum(w * h for ps in placed_sheets for (_x, _y, w, h, _l) in ps)
        capacity = len(placed_sheets) * sheet.length * sheet.width
        out.append({
            "stock": g["stock"],
            "thickness": g["thickness"],
            "sheet_length": sheet.length,
            "sheet_width": sheet.width,
            "sheet_count": len(placed_sheets),
            "utilization": (used / capacity) if capacity else 0.0,
            "oversize": oversize,
            "sheets": sheets,
        })
    return out
