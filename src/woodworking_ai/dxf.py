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
from .estimator import SheetSize
from .packing import pack as _pack_positions  # shared shelf nester


def _line(x1, y1, x2, y2, layer="PANEL") -> list[str]:
    return ["0", "LINE", "8", layer,
            "10", f"{x1:.2f}", "20", f"{y1:.2f}", "30", "0.0",
            "11", f"{x2:.2f}", "21", f"{y2:.2f}", "31", "0.0"]


def _rect(x, y, w, h, layer="PANEL") -> list[str]:
    return (_line(x, y, x + w, y, layer) + _line(x + w, y, x + w, y + h, layer)
            + _line(x + w, y + h, x, y + h, layer) + _line(x, y + h, x, y, layer))


def _text(x, y, height, s, layer="LABEL") -> list[str]:
    return ["0", "TEXT", "8", layer,
            "10", f"{x:.2f}", "20", f"{y:.2f}", "30", "0.0",
            "40", f"{height:.1f}", "1", s]


def _cutlist_items(cl: CutList) -> list[tuple[float, float, str]]:
    items: list[tuple[float, float, str]] = []
    for p in cl.parts:
        for i in range(p.qty):
            label = p.name if p.qty == 1 else f"{p.name} {i + 1}"
            items.append((p.length, p.width, label))
    return items


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

    out: list[str] = ["0", "SECTION", "2", "ENTITIES"]
    for s_idx, placements in enumerate(sheets):
        ox = s_idx * (sheet.length + gap)
        out += _rect(ox, 0, sheet.length, sheet.width, layer="SHEET")
        out += _text(ox + 5, sheet.width + 30, 40, f"Sheet {s_idx + 1}",
                     layer="SHEET")
        for (x, y, l, w, label) in placements:
            out += _rect(ox + x, y, l, w)
            out += _text(ox + x + 8, y + w / 2 - 8, 16,
                         f"{label} {l:.0f}x{w:.0f}")
    if oversize:
        out += _text(0, -60, 24,
                     f"OVERSIZE (not nested): {', '.join(oversize)}", "WARN")
    out += ["0", "ENDSEC", "0", "EOF"]

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
