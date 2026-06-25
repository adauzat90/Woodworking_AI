"""Assemble a complete design result from a spec.

One place that turns a :class:`CabinetSpec` into the full JSON-serialisable
bundle the web app (and any other front end) needs: validation, critique, cut
list, hardware, cost estimate, drilling schedule, a render PNG, and an
interactive GLB. Heavy/optional steps (render, GLB) degrade gracefully.
"""

from __future__ import annotations

import base64
import math
import tempfile
from pathlib import Path
from typing import Any

from .dsl import CabinetSpec
from .validator import validate
from .cutlist import generate_cutlist
from .estimator import estimate
from .drilling import drilling_schedule
from .agents.critic import critique


def _clean(obj: Any) -> Any:
    """Recursively replace non-finite floats (NaN/inf) with None.

    Guarantees the bundle is strict-JSON serialisable even when an invalid spec
    (e.g. a NaN dimension) is echoed back in an error response.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _b64_file(path: Path, mime: str) -> str:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _render_png(spec: CabinetSpec) -> str | None:
    try:
        from .render import render_cabinet
        with tempfile.TemporaryDirectory() as d:
            p = render_cabinet(spec, Path(d) / "c.png")
            return _b64_file(p, "image/png")
    except Exception:
        return None


def _glb(spec: CabinetSpec) -> str | None:
    try:
        from .builder import build_model
        from .exporters import export_glb
        with tempfile.TemporaryDirectory() as d:
            model = build_model(spec)
            p = export_glb(model, Path(d) / "c.glb")
            return _b64_file(p, "model/gltf-binary")
    except Exception:
        return None


def export_bytes(spec, fmt: str,
                 units: str = "metric") -> tuple[bytes, str, str]:
    """Return (data, media_type, filename) for a downloadable export.

    ``units="imperial"`` renders the cut list in fractional inches. The 32mm
    drilling schedule stays metric — it *is* a metric boring system.

    Raises ValueError for an unknown format and RuntimeError if a CAD format is
    requested without build123d installed.
    """
    fmt = fmt.lower()
    base = (spec.name or "cabinet").replace(" ", "_")

    if fmt in ("cutlist", "hardware", "drilling"):
        if fmt == "drilling":
            text = drilling_schedule(spec).to_csv()
        else:
            cl = generate_cutlist(spec)
            text = cl.to_csv(units) if fmt == "cutlist" else cl.hardware_csv()
        return text.encode("utf-8"), "text/csv", f"{base}_{fmt}.csv"

    if fmt == "dxf":
        from .dxf import export_cutlayout_dxf
        with tempfile.TemporaryDirectory() as d:
            p = export_cutlayout_dxf(spec, Path(d) / "layout.dxf")
            return p.read_bytes(), "application/dxf", f"{base}_cutlayout.dxf"

    if fmt in ("step", "stl", "glb"):
        from .builder import build_model
        from . import exporters
        fn = {"step": exporters.export_step, "stl": exporters.export_stl,
              "glb": exporters.export_glb}[fmt]
        mime = {"step": "application/step", "stl": "model/stl",
                "glb": "model/gltf-binary"}[fmt]
        with tempfile.TemporaryDirectory() as d:
            model = build_model(spec)
            p = fn(model, Path(d) / f"c.{fmt}")
            return p.read_bytes(), mime, f"{base}.{fmt}"

    raise ValueError(f"unknown export format: {fmt}")


def build_result(spec, *, want_png: bool = True, want_glb: bool = True,
                 prices=None, sheet=None) -> dict[str, Any]:
    """Full design bundle for *spec* — a cabinet, table, or whole project.

    Always JSON-serialisable; aggregate stages (cut list, cost, drilling,
    critic, render) dispatch on the spec type, so a Project returns the combined
    run bundle. ``prices`` (a :class:`PriceBook`) and ``sheet`` (a
    :class:`SheetSize`) override the costing defaults when supplied.
    """
    v = validate(spec)
    result: dict[str, Any] = {
        "spec": spec.to_dict(),
        "valid": v.ok,
        "warnings": [{"field": i.field, "message": i.message} for i in v.warnings],
        "errors": [{"field": i.field, "message": i.message} for i in v.errors],
        "advisories": [{"field": i.field, "message": i.message} for i in v.infos],
    }
    if not v.ok:
        # A broken spec: report the errors, skip the expensive downstream work.
        return _clean(result)

    crit = critique(spec)
    result["critique"] = {
        "ok": crit.ok,
        "report": crit.report,
        "issues": [{"severity": i.severity, "kind": i.kind, "message": i.message}
                   for i in crit.issues],
    }

    cl = generate_cutlist(spec)
    result["cutlist"] = [
        {"id": p.id, "name": p.name, "qty": p.qty, "length": round(p.length, 1),
         "width": round(p.width, 1), "thickness": p.thickness,
         "material": p.material, "grain": p.grain, "notes": p.notes}
        for p in cl.parts
    ]
    result["hardware"] = [
        {"name": h.name, "qty": h.qty, "notes": h.notes} for h in cl.hardware
    ]
    result["cutlist_summary"] = cl.summary()

    # Solid-lumber requirement in board feet / running length. Empty for an
    # all-sheet-goods cabinet; populated for tables, face frames, etc.
    lumber_groups = cl.lumber_breakdown()
    result["lumber"] = {
        "board_feet": round(cl.total_board_feet, 2),
        "groups": [
            {"material": g["material"], "thickness": g["thickness"],
             "parts": g["parts"], "board_feet": round(g["board_feet"], 2),
             "length_mm": round(g["length_mm"], 1)}
            for g in lumber_groups
        ],
    }

    est = estimate(spec, cutlist=cl, prices=prices, sheet=sheet)
    result["estimate"] = {
        "currency": est.currency,
        "total": round(est.total, 2),
        "material": round(est.material_cost, 2),
        "lumber": round(est.lumber_cost, 2),
        "board_feet": round(est.total_board_feet, 2),
        "hardware": round(est.hardware_cost, 2),
        "edge_banding": round(est.edge_banding_cost, 2),
        "labour": round(est.labour_cost, 2),
        "labour_hours": round(est.labour_hours, 1),
        "total_sheets": est.total_sheets,
        "groups": [
            {"material": g.material, "thickness": g.thickness,
             "parts": g.part_count, "sheets": g.sheets,
             "utilization": round(g.utilization, 3), "oversize": g.oversize}
            for g in est.groups
        ],
        "lumber_groups": [
            {"material": g.material, "thickness": g.thickness,
             "parts": g.part_count, "board_feet": round(g.board_feet, 2),
             "cost": round(g.cost, 2)}
            for g in est.lumber_groups
        ],
    }

    drill = drilling_schedule(spec)
    result["drilling"] = {
        "total_holes": drill.total_holes,
        "ops": [{"part": o.part, "part_id": o.part_id, "operation": o.operation,
                 "holes": len(o.holes), "note": o.note,
                 # Per-hole positions so the UI can show exactly where to bore.
                 # Coordinates are metric (the 32mm boring system is metric).
                 "hole_list": [
                     {"face": h.face, "u": round(h.u, 1), "v": round(h.v, 1),
                      "dia": h.dia, "depth": h.depth, "note": h.note}
                     for h in o.holes
                 ]}
                for o in drill.ops],
    }

    result["render_png"] = _render_png(spec) if want_png else None
    result["glb"] = _glb(spec) if want_glb else None
    return _clean(result)
