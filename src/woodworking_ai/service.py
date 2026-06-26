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
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from .dsl import CabinetSpec
from .validator import validate
from .cutlist import generate_cutlist
from .estimator import estimate
from .drilling import drilling_schedule
from .joinery import joinery_schedule
from .assembly_steps import assembly_plan
from .stock import stock_label as _stock_label, stock_product as _stock_product
from .materials import stock_name as _stock_name, product_hint as _product_hint
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


def _stock_fields(form: str, species: str, material: str,
                  *, solid: bool) -> dict[str, str]:
    """Buyer-facing ``stock``/``product`` names for a cost/lumber group.

    Falls back to the legacy usage-label naming when no form/species is declared,
    so every group surfaces the same physical-stock vocabulary as the report.
    """
    return {
        "stock": _stock_name(form, species, solid=solid,
                             fallback=_stock_label(material)),
        "product": _product_hint(form, _stock_product(material)),
    }


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


def model_glb_bytes(spec, *, factor: float = 0.0,
                    include: set | None = None) -> bytes:
    """GLB bytes for *spec* — assembled, exploded (``factor`` > 0), or a
    progressive subset (``include`` = sub-assembly names). Needs build123d."""
    from .builder import build_model
    from .exporters import export_glb
    with tempfile.TemporaryDirectory() as d:
        model = build_model(spec, factor=factor, include=include)
        p = export_glb(model, Path(d) / "m.glb")
        return p.read_bytes()


def export_bytes(spec, fmt: str,
                 units: str = "metric",
                 joinery_geometry: bool = False) -> tuple[bytes, str, str]:
    """Return (data, media_type, filename) for a downloadable export.

    ``units="imperial"`` renders the cut list in fractional inches. The 32mm
    drilling schedule stays metric — it *is* a metric boring system.
    ``joinery_geometry=True`` cuts dados/rabbets/grooves and bores into the
    exported CAD B-Rep (step/stl/glb); it is ignored by the non-CAD formats.

    Raises ValueError for an unknown format and RuntimeError if a CAD format is
    requested without build123d installed.
    """
    fmt = fmt.lower()
    base = (spec.name or "cabinet").replace(" ", "_")

    if fmt in ("cutlist", "hardware", "drilling", "joinery", "purchase_order"):
        if fmt == "drilling":
            text = drilling_schedule(spec).to_csv()
        elif fmt == "joinery":
            text = joinery_schedule(spec).to_csv()
        elif fmt == "purchase_order":
            from .purchasing import purchase_order
            text = purchase_order(spec).to_csv()
        else:
            cl = generate_cutlist(spec)
            text = cl.to_csv(units) if fmt == "cutlist" else cl.hardware_csv()
        return text.encode("utf-8"), "text/csv", f"{base}_{fmt}.csv"

    if fmt == "dxf":
        from .dxf import export_cutlayout_dxf
        with tempfile.TemporaryDirectory() as d:
            p = export_cutlayout_dxf(spec, Path(d) / "layout.dxf")
            return p.read_bytes(), "application/dxf", f"{base}_cutlayout.dxf"

    if fmt == "drawings":
        from .drawings import render_svg
        svg = render_svg(spec, units)
        return svg.encode("utf-8"), "image/svg+xml", f"{base}_drawings.svg"

    if fmt == "package":
        from .report import build_package_pdf
        data = build_package_pdf(spec, units=units)
        return data, "application/pdf", f"{base}_build_package.pdf"

    if fmt == "proposal":
        from .proposal import build_proposal_pdf
        data = build_proposal_pdf(spec, units=units)
        return data, "application/pdf", f"{base}_proposal.pdf"

    if fmt == "template":
        from .report import build_template_pdf
        data = build_template_pdf(spec, units=units)
        return data, "application/pdf", f"{base}_template.pdf"

    if fmt == "purchase_order_pdf":
        from .report import build_purchase_order_pdf
        data = build_purchase_order_pdf(spec, units=units)
        return data, "application/pdf", f"{base}_purchase_order.pdf"

    if fmt in ("step", "stl", "glb", "dae"):
        from .builder import build_model
        from . import exporters
        fn = {"step": exporters.export_step, "stl": exporters.export_stl,
              "glb": exporters.export_glb, "dae": exporters.export_dae}[fmt]
        mime = {"step": "application/step", "stl": "model/stl",
                "glb": "model/gltf-binary",
                "dae": "model/vnd.collada+xml"}[fmt]
        with tempfile.TemporaryDirectory() as d:
            model = build_model(spec, joinery_geometry=joinery_geometry)
            p = fn(model, Path(d) / f"c.{fmt}")
            return p.read_bytes(), mime, f"{base}.{fmt}"

    raise ValueError(f"unknown export format: {fmt}")


@dataclass
class Assembly:
    """The pipeline run for one spec, computed once and shared.

    Holds the live domain objects (validation result, critique, cut list, and
    the on-demand estimate/drilling/joinery/assembly schedules) so a front end
    can render them however it likes. The web bundle (:func:`build_result`) and
    the CLI both flow through here instead of each re-running the pipeline.

    The always-needed stages (validate, critique, cut list) are computed eagerly;
    the rest are :class:`cached_property` so callers pay only for what they show.
    """

    spec: Any
    prices: Any = None
    sheet: Any = None
    tooling: Any = None

    @cached_property
    def validation(self):
        return validate(self.spec, tooling=self.tooling)

    @cached_property
    def critique(self):
        return critique(self.spec)

    @cached_property
    def cutlist(self):
        return generate_cutlist(self.spec)

    @cached_property
    def estimate(self):
        return estimate(self.spec, cutlist=self.cutlist,
                        prices=self.prices, sheet=self.sheet)

    @cached_property
    def drilling(self):
        return drilling_schedule(self.spec)

    @cached_property
    def joinery(self):
        return joinery_schedule(self.spec)

    @cached_property
    def assembly(self):
        return assembly_plan(self.spec)

    @cached_property
    def plan(self):
        from .planning import plan as _plan
        return _plan(self.spec, self.tooling)


def assemble(spec, *, prices=None, sheet=None, tooling=None) -> Assembly:
    """Run (lazily) the design pipeline for *spec* once, returning live objects.

    The single entry point both the CLI and :func:`build_result` use so the two
    front ends can never drift on defaults or skip a stage. ``prices``/``sheet``
    override the costing defaults when supplied; ``tooling`` (a
    :class:`~tooling.ShopTooling`) constrains validation to makeable joinery.
    """
    return Assembly(spec, prices=prices, sheet=sheet, tooling=tooling)


def cutplan_result(spec, boards, *, cutlist=None, kerf: float = 3.0) -> dict[str, Any]:
    """JSON-serialisable "cut from my stock" plan for *spec* given owned *boards*.

    *boards* is a list of :class:`~woodworking_ai.cutplan.StockBoard` (or dicts).
    Returns per-board placements + offcuts + yield and a shortfall list — the
    parts that did not fit any owned board (what still to buy). Pure-math; no CAD
    dependency. Returned standalone and (optionally) embedded by
    :func:`build_result` when boards are supplied.
    """
    from .cutplan import cut_plan, boards_from_dicts
    if boards and isinstance(boards[0], dict):
        boards = boards_from_dicts(boards)
    plan = cut_plan(spec, list(boards), cutlist=cutlist, kerf=kerf)
    return {
        "spec_name": plan.spec_name,
        "complete": plan.complete,
        "kerf": plan.kerf,
        "placed_count": plan.placed_count,
        "boards_used": plan.boards_used,
        "yield": round(plan.yield_pct, 3),
        "used_area_m2": round(plan.used_area_m2, 4),
        "offcut_area_m2": round(plan.offcut_area_m2, 4),
        "boards": [
            {
                "id": bp.board.id or "",
                "length": bp.board.length, "width": bp.board.width,
                "thickness": bp.board.thickness,
                "form": bp.board.form, "species": bp.board.species,
                "instance": bp.instance,
                "part_count": bp.part_count,
                "yield": round(bp.yield_pct, 3),
                "offcut_area_m2": round(bp.offcut_area_m2, 4),
                "placements": [
                    {"part_id": p.part_id, "label": p.label,
                     "x": round(p.x, 1), "y": round(p.y, 1),
                     "length": round(p.length, 1), "width": round(p.width, 1)}
                    for p in bp.placements
                ],
            }
            for bp in plan.boards if bp.placements
        ],
        "shortfall": [
            {"part_id": s.part_id, "label": s.label,
             "length": round(s.length, 1), "width": round(s.width, 1),
             "thickness": s.thickness, "form": s.form, "species": s.species,
             "reason": s.reason}
            for s in plan.shortfall
        ],
    }


def build_result(spec, *, want_png: bool = True, want_glb: bool = True,
                 prices=None, sheet=None, tooling=None,
                 boards=None) -> dict[str, Any]:
    """Full design bundle for *spec* — a cabinet, table, or whole project.

    Always JSON-serialisable; aggregate stages (cut list, cost, drilling,
    critic, render) dispatch on the spec type, so a Project returns the combined
    run bundle. ``prices`` (a :class:`PriceBook`) and ``sheet`` (a
    :class:`SheetSize`) override the costing defaults when supplied.

    ``boards`` (a list of :class:`~woodworking_ai.cutplan.StockBoard` or dicts),
    when supplied, adds an OPTIONAL ``cutplan`` section assigning the parts to
    the owned stock. Omitted entirely when no boards are given, so the bundle is
    fully backward compatible.
    """
    asm = assemble(spec, prices=prices, sheet=sheet, tooling=tooling)
    v = asm.validation
    result: dict[str, Any] = {
        "spec": spec.to_dict(),
        "valid": v.ok,
        "warnings": [{"field": i.field, "message": i.message} for i in v.warnings],
        "errors": [{"field": i.field, "message": i.message} for i in v.errors],
        "advisories": [{"field": i.field, "message": i.message} for i in v.infos],
    }

    # Tool/jig checklist for the build — marked owned/missing when an inventory
    # was given, otherwise just the list of what the joinery needs.
    from .tooling import tools_needed
    result["tools"] = [
        {"operation": t.operation, "tool": t.tool, "where": t.where,
         "owned": t.owned}
        for t in tools_needed(spec, tooling)
    ]
    if not v.ok:
        # A broken spec: report the errors, skip the expensive downstream work.
        return _clean(result)

    crit = asm.critique
    result["critique"] = {
        "ok": crit.ok,
        "report": crit.report,
        "issues": [{"severity": i.severity, "kind": i.kind, "message": i.message}
                   for i in crit.issues],
    }

    cl = asm.cutlist
    result["cutlist"] = [
        {"id": p.id, "name": p.name, "qty": p.qty, "length": round(p.length, 1),
         "width": round(p.width, 1), "thickness": p.thickness,
         "material": p.material, "grain": p.grain, "notes": p.notes,
         "form": p.form, "species": p.species,
         "stock": _stock_name(p.form, p.species, solid=p.is_solid_lumber,
                              fallback=_stock_label(p.material))}
        for p in cl.parts
    ]
    result["hardware"] = [
        {"name": h.name, "qty": h.qty, "brand": h.brand, "sku": h.sku,
         "category": h.category, "notes": h.notes} for h in cl.hardware
    ]
    result["cutlist_summary"] = cl.summary()

    # Sheet-nesting placements for the visual cut diagram — the same pack the
    # cost estimate counts sheets from, so the diagram and the quote agree.
    from .nesting import nest_layout
    result["nesting"] = nest_layout(spec, sheet=sheet, cutlist=cl)

    # Optional "cut from my stock" plan — only when the caller supplied owned
    # boards, so the bundle is unchanged for every existing caller.
    if boards:
        result["cutplan"] = cutplan_result(spec, boards, cutlist=cl)

    # Solid-lumber requirement in board feet / running length. Empty for an
    # all-sheet-goods cabinet; populated for tables, face frames, etc.
    lumber_groups = cl.lumber_breakdown()
    result["lumber"] = {
        "board_feet": round(cl.total_board_feet, 2),
        "groups": [
            {"material": g["material"],
             **_stock_fields(g.get("form", ""), g.get("species", ""),
                             g["material"], solid=True),
             "thickness": g["thickness"],
             "form": g.get("form", ""), "species": g.get("species", ""),
             "parts": g["parts"], "board_feet": round(g["board_feet"], 2),
             "length_mm": round(g["length_mm"], 1)}
            for g in lumber_groups
        ],
    }

    est = asm.estimate
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
        "finish": round(est.finish_cost, 2),
        "finish_m2": round(est.finish_m2, 2),
        "total_sheets": est.total_sheets,
        "groups": [
            {"material": g.material,
             **_stock_fields(g.form, g.species, g.material, solid=False),
             "thickness": g.thickness,
             "form": g.form, "species": g.species,
             "parts": g.part_count, "sheets": g.sheets,
             "utilization": round(g.utilization, 3), "oversize": g.oversize}
            for g in est.groups
        ],
        "lumber_groups": [
            {"material": g.material,
             **_stock_fields(g.form, g.species, g.material, solid=True),
             "thickness": g.thickness,
             "form": g.form, "species": g.species,
             "parts": g.part_count, "board_feet": round(g.board_feet, 2),
             "cost": round(g.cost, 2)}
            for g in est.lumber_groups
        ],
    }

    # Purchase order — the orderable buy-list grouped by supplier/brand. Its
    # grand total reconciles with the estimate above (same prices/sheet).
    from .purchasing import purchase_order
    po = purchase_order(spec, prices=prices, sheet=sheet, cutlist=cl)
    def _po_line(ln):
        return {"supplier": ln.supplier, "category": ln.category, "item": ln.item,
                "spec": ln.spec, "qty": round(ln.qty, 3), "unit": ln.unit,
                "brand": ln.brand, "sku": ln.sku,
                "unit_price": round(ln.unit_price, 4),
                "line_total": round(ln.line_total, 2),
                "source": ln.source, "url": ln.url, "alt": ln.alt}

    result["purchase_order"] = {
        "currency": po.currency,
        "grand_total": round(po.grand_total, 2),
        "consumables_total": round(po.consumables_total, 2),
        "suppliers": [
            {"supplier": s, "subtotal": round(po.supplier_total(s), 2)}
            for s in po.suppliers
        ],
        "lines": [_po_line(ln) for ln in po.lines],
        "consumables": [_po_line(ln) for ln in po.consumables],
    }

    drill = asm.drilling
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

    joint = asm.joinery
    result["joinery"] = [
        {"part": o.part, "part_id": o.part_id, "operation": o.operation,
         "tool": o.tool, "width": round(o.width, 1), "depth": round(o.depth, 1),
         "reference": o.reference, "note": o.note}
        for o in joint.ops
    ]

    from .finishing import finishing_schedule
    result["finishing"] = finishing_schedule(spec)

    # Build plan — skill rating + method-aware phase time breakdown. Additive;
    # the time model keys off `tooling` (hand vs. jig vs. machine) when supplied,
    # and falls back to a stable well-equipped default when it is None.
    result["plan"] = asm.plan

    # Appliance schedule — present only when the design has appliances, so the
    # web bundle can show the section conditionally (mirrors the report).
    from .appliances import appliance_schedule
    result["appliances"] = appliance_schedule(spec)

    plan = asm.assembly
    result["assembly"] = [
        {"name": sub.name, "detail": sub.detail, "part_ids": sub.part_ids,
         "category": sub.category,
         "steps": [
             {"number": s.number, "title": s.title, "detail": s.detail,
              "part_ids": s.part_ids, "hardware": s.hardware,
              "category": s.category}
             for s in sub.steps]}
        for sub in plan.subassemblies
    ]

    # The 3D model's sub-assemblies, in build order — drives the build-view
    # stepper and the exploded view (always available, even without build123d).
    try:
        from .geometry import panels_by_subassembly
        result["model_sections"] = list(panels_by_subassembly(spec).keys())
    except Exception:
        result["model_sections"] = []

    try:
        from .drawings import render_svg
        result["drawings_svg"] = render_svg(spec, "metric")
    except Exception:
        result["drawings_svg"] = None

    result["render_png"] = _render_png(spec) if want_png else None
    result["glb"] = _glb(spec) if want_glb else None
    return _clean(result)
