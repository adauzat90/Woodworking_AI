"""Assemble a complete design result from a spec.

One place that turns a :class:`CabinetSpec` into the full JSON-serialisable
bundle the web app (and any other front end) needs: validation, critique, cut
list, hardware, cost estimate, drilling schedule, a render PNG, and an
interactive GLB. Heavy/optional steps (render, GLB) degrade gracefully.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from .dsl import CabinetSpec
from .validator import validate
from .cutlist import generate_cutlist
from .estimator import estimate
from .drilling import drilling_schedule
from .agents.critic import critique


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


def build_result(spec: CabinetSpec, *, want_png: bool = True,
                 want_glb: bool = True) -> dict[str, Any]:
    """Full design bundle for *spec* (always JSON-serialisable)."""
    v = validate(spec)
    result: dict[str, Any] = {
        "spec": spec.to_dict(),
        "valid": v.ok,
        "warnings": [{"field": i.field, "message": i.message} for i in v.warnings],
        "errors": [{"field": i.field, "message": i.message} for i in v.errors],
    }
    if not v.ok:
        # A broken spec: report the errors, skip the expensive downstream work.
        return result

    crit = critique(spec)
    result["critique"] = {
        "ok": crit.ok,
        "report": crit.report,
        "issues": [{"severity": i.severity, "kind": i.kind, "message": i.message}
                   for i in crit.issues],
    }

    cl = generate_cutlist(spec)
    result["cutlist"] = [
        {"name": p.name, "qty": p.qty, "length": round(p.length, 1),
         "width": round(p.width, 1), "thickness": p.thickness,
         "material": p.material, "notes": p.notes}
        for p in cl.parts
    ]
    result["hardware"] = [
        {"name": h.name, "qty": h.qty, "notes": h.notes} for h in cl.hardware
    ]
    result["cutlist_summary"] = cl.summary()

    est = estimate(spec, cutlist=cl)
    result["estimate"] = {
        "currency": est.currency,
        "total": round(est.total, 2),
        "material": round(est.material_cost, 2),
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
    }

    drill = drilling_schedule(spec)
    result["drilling"] = {
        "total_holes": drill.total_holes,
        "ops": [{"part": o.part, "operation": o.operation,
                 "holes": len(o.holes), "note": o.note} for o in drill.ops],
    }

    result["render_png"] = _render_png(spec) if want_png else None
    result["glb"] = _glb(spec) if want_glb else None
    return result
