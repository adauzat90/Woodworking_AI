"""DXF cut-layout (nesting diagram) export.

Lays the cut-list panels onto standard sheets with the same shelf-nesting used
by the estimator and writes a 2D DXF a shop or CNC nest program can open. Each
panel is a labelled rectangle; sheets are tiled left-to-right.

Writes plain ASCII DXF (R12: LINE + TEXT entities) directly, so there is **no
CAD dependency** — it runs anywhere the cut list does.
"""

from __future__ import annotations

from pathlib import Path

from .dsl import CabinetSpec
from .cutlist import CutList, generate_cutlist
from .drilling import (
    drilling_schedule, holes_by_part_id, ops_for_instance, place_holes,
)
from .estimator import SheetSize
from .packing import pack as _pack_positions  # shared shelf nester

# DXF layers a CAM post can map to tools. PANEL/SHEET/LABEL carry the nest; the
# machining layers split bores (drilled) from grooves (routed) so a post can
# assign a drill vs a router bit per layer. A1 populates BORE; DADO/RABBET are
# declared here but filled by a later item. CUTOUT carries sink/cooktop openings
# routed clean through a countertop.
_LAYERS = ("PANEL", "SHEET", "LABEL", "WARN", "BORE", "DADO", "RABBET", "CUTOUT")


def _line(x1, y1, x2, y2, layer="PANEL") -> list[str]:
    return ["0", "LINE", "8", layer,
            "10", f"{x1:.2f}", "20", f"{y1:.2f}", "30", "0.0",
            "11", f"{x2:.2f}", "21", f"{y2:.2f}", "31", "0.0"]


def _rect(x, y, w, h, layer="PANEL") -> list[str]:
    return (_line(x, y, x + w, y, layer) + _line(x + w, y, x + w, y + h, layer)
            + _line(x + w, y + h, x, y + h, layer) + _line(x, y + h, x, y, layer))


def _circle(cx, cy, r, layer="BORE") -> list[str]:
    return ["0", "CIRCLE", "8", layer,
            "10", f"{cx:.2f}", "20", f"{cy:.2f}", "30", "0.0", "40", f"{r:.2f}"]


def _text(x, y, height, s, layer="LABEL") -> list[str]:
    return ["0", "TEXT", "8", layer,
            "10", f"{x:.2f}", "20", f"{y:.2f}", "30", "0.0",
            "40", f"{height:.1f}", "1", s]


def _layer_table() -> list[str]:
    """A minimal R12 LAYER table so every machining layer exists in the file."""
    out = ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER",
           "70", str(len(_LAYERS))]
    for name in _LAYERS:
        out += ["0", "LAYER", "2", name, "70", "0", "62", "7", "6", "CONTINUOUS"]
    out += ["0", "ENDTAB", "0", "ENDSEC"]
    return out


def _bore_tag(h, thickness: float) -> str:
    """Short diameter tag: ``⌀5`` through, ``⌀35x12.5`` for a stopped bore.

    A bore is "stopped" when it does not pass through the stock (depth < the
    part thickness); those carry the depth so the post drills to it.
    """
    stopped = 0 < h.depth < thickness - 1e-6
    return f"⌀{h.dia:g}x{h.depth:g}" if stopped else f"⌀{h.dia:g}"


def _cutlist_items(cl: CutList) -> list[tuple]:
    items: list[tuple] = []
    for p in cl.parts:
        code = f"{p.id} " if p.id else ""
        seq = "front" if p.material == "door/front" else ""
        for i in range(p.qty):
            label = (f"{code}{p.name}" if p.qty == 1
                     else f"{code}{p.name} {i + 1}")
            items.append((p.length, p.width, label, p.grain, seq))
    return items


def _placement_part(label: str, by_id: dict):
    """Resolve a placement label to ``(part, instance)`` (or ``(None, 1)``).

    Labels are ``"{id} {name}"`` (qty 1) or ``"{id} {name} {i}"`` (qty>1), as
    emitted by :func:`_cutlist_items`; the part code is the first token and the
    1-based instance is the trailing integer when the part is multi-qty.
    """
    pid = label.split(" ", 1)[0]
    part = by_id.get(pid)
    if part is None:
        return None, 1
    instance = 1
    if part.qty > 1:
        last = label.rsplit(" ", 1)[-1]
        instance = int(last) if last.isdigit() else 1
    return part, instance


def _cutouts_for_placement(part, x, y, l, w) -> list[str]:
    """DXF closed polylines for every cut-out on one placed part.

    Each opening is ``(ox, oy, ow, od)`` in the part's own (length × width)
    frame; mapped into the placed rectangle honouring the nester's rotation
    (the same convention :func:`place_holes` uses), then drawn as a rectangle
    on the CUTOUT layer.
    """
    from .drilling import _placement_rotated
    out: list[str] = []
    openings = getattr(part, "openings", None) or []
    rotated = _placement_rotated(part.length, part.width, l, w)
    for (ox, oy, ow, od) in openings:
        if rotated:              # part.width runs along the sheet x-axis
            rx, ry, rw, rh = x + oy, y + ox, od, ow
        else:                    # part.length runs along the sheet x-axis
            rx, ry, rw, rh = x + ox, y + oy, ow, od
        out += _rect(rx, ry, rw, rh, layer="CUTOUT")
    return out


def _bores_for_placement(part, instance, ops, x, y, l, w) -> list[str]:
    """DXF entities for every bore on one placed part instance."""
    out: list[str] = []
    holes = [h for op in ops_for_instance(ops, instance, part.qty)
             for h in op.holes]
    for (cx, cy, h) in place_holes(holes, part.length, part.width, x, y, l, w):
        out += _circle(cx, cy, h.dia / 2.0, layer="BORE")
        out += _text(cx + h.dia / 2.0 + 1, cy - 4, 7,
                     _bore_tag(h, part.thickness), layer="BORE")
    return out


def export_cutlayout_dxf(spec: CabinetSpec, path: str | Path, *,
                         cutlist: CutList | None = None,
                         sheet: SheetSize | None = None) -> Path:
    """Write a nested cut-layout DXF for *spec*; returns the path."""
    cl = cutlist or generate_cutlist(spec)
    sheet = sheet or SheetSize()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sheets, oversize = _pack_positions(_cutlist_items(cl), sheet)
    gap = 200.0  # space between sheets on the drawing

    # Drilling bores, keyed to the same cut-list part code carried by every
    # placement, so each panel's holes follow it to wherever it nests.
    by_id = {p.id: p for p in cl.parts if p.id}
    ops_by_id = holes_by_part_id(drilling_schedule(spec))

    out: list[str] = _layer_table()
    out += ["0", "SECTION", "2", "ENTITIES"]
    for s_idx, placements in enumerate(sheets):
        ox = s_idx * (sheet.length + gap)
        out += _rect(ox, 0, sheet.length, sheet.width, layer="SHEET")
        out += _text(ox + 5, sheet.width + 30, 40, f"Sheet {s_idx + 1}",
                     layer="SHEET")
        for (x, y, l, w, label) in placements:
            out += _rect(ox + x, y, l, w)
            out += _text(ox + x + 8, y + w / 2 - 8, 16,
                         f"{label} {l:.0f}x{w:.0f}")
            part, instance = _placement_part(label, by_id)
            ops = ops_by_id.get(part.id) if part is not None else None
            if ops:
                out += _bores_for_placement(part, instance, ops,
                                            ox + x, y, l, w)
            if part is not None and getattr(part, "openings", None):
                out += _cutouts_for_placement(part, ox + x, y, l, w)
    if oversize:
        out += _text(0, -60, 24,
                     f"OVERSIZE (not nested): {', '.join(oversize)}", "WARN")
    out += ["0", "ENDSEC", "0", "EOF"]

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
