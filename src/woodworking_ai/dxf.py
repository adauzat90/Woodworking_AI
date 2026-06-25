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
    placement_rotated, place_rect, drilling_schedule, holes_by_part_id,
    ops_for_instance, place_holes,
)
from .joinery import joinery_schedule
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


def rect(x, y, w, h, layer="PANEL") -> list[str]:
    return (_line(x, y, x + w, y, layer) + _line(x + w, y, x + w, y + h, layer)
            + _line(x + w, y + h, x, y + h, layer) + _line(x, y + h, x, y, layer))


def _circle(cx, cy, r, layer="BORE") -> list[str]:
    return ["0", "CIRCLE", "8", layer,
            "10", f"{cx:.2f}", "20", f"{cy:.2f}", "30", "0.0", "40", f"{r:.2f}"]


def text(x, y, height, s, layer="LABEL") -> list[str]:
    return ["0", "TEXT", "8", layer,
            "10", f"{x:.2f}", "20", f"{y:.2f}", "30", "0.0",
            "40", f"{height:.1f}", "1", s]


def layer_table() -> list[str]:
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
    out: list[str] = []
    openings = getattr(part, "openings", None) or []
    rotated = placement_rotated(part.length, part.width, l, w)
    for (ox, oy, ow, od) in openings:
        rx, ry, rw, rh = place_rect(rotated, x, y, oy, ox, od, ow)
        out += rect(rx, ry, rw, rh, layer="CUTOUT")
    return out


def _bores_for_placement(part, instance, ops, x, y, l, w) -> list[str]:
    """DXF entities for every bore on one placed part instance."""
    out: list[str] = []
    holes = [h for op in ops_for_instance(ops, instance, part.qty)
             for h in op.holes]
    for (cx, cy, h) in place_holes(holes, part.length, part.width, x, y, l, w):
        out += _circle(cx, cy, h.dia / 2.0, layer="BORE")
        out += text(cx + h.dia / 2.0 + 1, cy - 4, 7,
                     _bore_tag(h, part.thickness), layer="BORE")
    return out


# --- joinery (housed dados / rabbets / grooves) -----------------------------
# A joinery op carries a cut ``width`` + ``depth`` and a *textual* ``reference``
# (e.g. "near the bottom edge", "rear edge") — there is no numeric coordinate in
# the schedule. So we draw each housed joint as a band of the cut ``width`` that
# spans the panel, placed by parsing the reference into one of a few edges. This
# is a deliberate, documented approximation: the band width is exact (it comes
# from the op), its position is to the named edge with a fixed inset, not a
# CAD-precise dimension. Point/edge joints (dowel, domino, pocket, dovetail,
# box) have no linear housing to draw, so they are skipped here.
_HOUSED_KEYWORDS = ("dado", "rabbet", "groove", "housing")

# How far the housing sits in from the named edge (mm). Bottom/top carcass
# joints and back grooves are inset by their own margins; everything else falls
# back to the centre of the panel.
_EDGE_INSET = 12.0


def joinery_by_part_id(sched) -> dict:
    """Group a joinery schedule's housed ops by their cut-list ``part_id``.

    Only ops that describe a linear housing (a dado/rabbet/groove carrying a
    real ``width`` and ``depth``) are kept; point joints (dowel/domino/pocket)
    and corner joints (dovetail/box) have no groove to draw on the face.

    Ops are de-duplicated per part by their *geometric* signature (operation,
    reference edge, width, depth). The schedule lists a housing once per hand
    ("Side L"/"Side R") but both hands of a part get the same dado in the same
    place, so we keep one and let every placed instance draw it — this is why a
    qty-N panel draws each housing N times (once per placement), not per op.
    """
    out: dict = {}
    seen: dict = {}
    for op in sched.ops:
        if not op.part_id or op.width <= 0 or op.depth <= 0:
            continue
        text = f"{op.operation} {op.tool}".lower()
        if not any(k in text for k in _HOUSED_KEYWORDS):
            continue
        sig = (op.part_id, op.operation, op.reference, op.width, op.depth)
        if sig in seen.setdefault(op.part_id, set()):
            continue
        seen[op.part_id].add(sig)
        out.setdefault(op.part_id, []).append(op)
    return out


def _housing_layer(op) -> str:
    """Pick the DXF layer for a housed joint: rabbets to RABBET, else DADO."""
    text = f"{op.operation} {op.tool}".lower()
    return "RABBET" if "rabbet" in text else "DADO"


def _housing_band(op, length: float, width: float):
    """Position one housing in the part's own (length × width) frame.

    Returns ``(u0, v0, span_u, span_v)`` — the band rectangle in part coords,
    where ``length`` runs along ``v`` is *not* assumed; we work directly in the
    part frame (u across width, v along length) and the caller maps it onto the
    placed rectangle honouring the nester's rotation.

    The reference text decides the edge:
      * "bottom"  → a cross-panel band near the v=0 (bottom) end
      * "top"     → a cross-panel band near the v=length (top) end
      * "rear"/"back" → a lengthwise band near the u=width (rear) edge
      * otherwise → a cross-panel band at the panel's mid-length
    The band thickness is the op's cut ``width``; its length spans the panel.
    """
    ref = (op.reference or "").lower()
    w = max(op.width, 1.0)              # drawn band thickness = cut width
    if "rear" in ref or "back" in ref:
        # Lengthwise groove just in from the back edge (u = width side).
        u0 = max(width - _EDGE_INSET - w, 0.0)
        return (u0, 0.0, w, length)
    if "top" in ref:
        v0 = max(length - _EDGE_INSET - w, 0.0)
        return (0.0, v0, width, w)
    if "bottom" in ref:
        return (0.0, _EDGE_INSET, width, w)
    # Unlocated housing (drawer-bottom groove, generic): centre it lengthwise.
    return (0.0, max(length / 2 - w / 2, 0.0), width, w)


def _joinery_for_placement(part, ops, x, y, l, w) -> list[str]:
    """DXF line entities for every housed joint on one placed part rectangle.

    *ops* is the de-duplicated housing set for this part (see
    :func:`joinery_by_part_id`). Each housing's part-frame band is mapped into
    the placed rectangle the same way bores are (honouring the nester's
    rotation) and drawn as a rectangle on the DADO/RABBET layer, so every placed
    instance of a qty-N panel carries its housings.
    """
    out: list[str] = []
    rotated = placement_rotated(part.length, part.width, l, w)
    for op in ops:
        u0, v0, su, sv = _housing_band(op, part.length, part.width)
        rx, ry, rw, rh = place_rect(rotated, x, y, u0, v0, su, sv)
        out += rect(rx, ry, rw, rh, layer=_housing_layer(op))
    return out


def export_cutlayout_dxf(spec: CabinetSpec, path: str | Path, *,
                         cutlist: CutList | None = None,
                         sheet: SheetSize | None = None,
                         joinery: bool = True) -> Path:
    """Write a nested cut-layout DXF for *spec*; returns the path.

    With ``joinery=True`` (default) each placed panel also gets its housed
    joints (dados / rabbets / grooves from :func:`joinery_schedule`) drawn on
    the DADO/RABBET layers, in addition to the bores already drawn on BORE.
    Set ``joinery=False`` to emit the outline-only nest (plus bores/cutouts).
    """
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
    # Housed joints (dados/rabbets/grooves), keyed to the same part code. A
    # housing follows its panel to wherever it nests, just like the bores.
    joinery_by_id = (joinery_by_part_id(joinery_schedule(spec))
                     if joinery else {})

    out: list[str] = layer_table()
    out += ["0", "SECTION", "2", "ENTITIES"]
    for s_idx, placements in enumerate(sheets):
        ox = s_idx * (sheet.length + gap)
        out += rect(ox, 0, sheet.length, sheet.width, layer="SHEET")
        out += text(ox + 5, sheet.width + 30, 40, f"Sheet {s_idx + 1}",
                     layer="SHEET")
        for (x, y, l, w, label) in placements:
            out += rect(ox + x, y, l, w)
            out += text(ox + x + 8, y + w / 2 - 8, 16,
                         f"{label} {l:.0f}x{w:.0f}")
            part, instance = _placement_part(label, by_id)
            ops = ops_by_id.get(part.id) if part is not None else None
            if ops:
                out += _bores_for_placement(part, instance, ops,
                                            ox + x, y, l, w)
            j_ops = joinery_by_id.get(part.id) if part is not None else None
            if j_ops:
                out += _joinery_for_placement(part, j_ops, ox + x, y, l, w)
            if part is not None and getattr(part, "openings", None):
                out += _cutouts_for_placement(part, ox + x, y, l, w)
    if oversize:
        out += text(0, -60, 24,
                     f"OVERSIZE (not nested): {', '.join(oversize)}", "WARN")
    out += ["0", "ENDSEC", "0", "EOF"]

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
